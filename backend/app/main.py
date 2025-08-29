import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from uuid import uuid4
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware

from firebase_admin import firestore

from app.deps.firebase import verify_id_token, get_db
from app.utils.fs import project_path, extract_zip_to
from app.utils.git import shallow_clone, get_head_sha

from app.analysis.static_tools import run_all
from app.analysis.ai_review import generate_review
from app.analysis.vpoints import build_vpoints


# -------------------------------
# Models
# -------------------------------

class ProjectCreate(BaseModel):
    name: str
    source: str   # "upload" | "github" | "git"

class JobCreate(BaseModel):
    projectId: str

class GithubImport(BaseModel):
    repoUrl: str
    branch: str | None = "main"
    name: str | None = None


# -------------------------------
# App & Env
# -------------------------------

app = FastAPI(title="AI Code Review API", version="0.4.0")

# Load .env (repo-root/backend/.env)
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Read after load_dotenv so it picks up the value
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

def _ts_val(x):
    return x if isinstance(x, datetime) else datetime.min

# In dev we use Vite proxy → CORS not needed, but safe to leave permissive.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Health
# -------------------------------

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


# -------------------------------
# Auth
# -------------------------------

bearer = HTTPBearer(auto_error=False)

def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        decoded = verify_id_token(creds.credentials)
        return decoded  # contains uid, email, etc.
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@app.get("/me")
def me(user=Depends(current_user)):
    db = get_db()
    uid = user["uid"]
    db.collection("users").document(uid).set({
        "uid": uid,
        "email": user.get("email"),
        "name": user.get("name"),
        "provider": user.get("firebase", {}).get("sign_in_provider"),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }, merge=True)
    return {
        "uid": uid,
        "email": user.get("email"),
        "name": user.get("name"),
        "provider": user.get("firebase", {}).get("sign_in_provider")
    }


# -------------------------------
# Projects
# -------------------------------

@app.post("/projects")
def create_project(data: ProjectCreate, user=Depends(current_user)):
    db = get_db()
    project_id = str(uuid4())
    db.collection("projects").document(project_id).set({
        "id": project_id,
        "uid": user["uid"],
        "name": data.name,
        "source": data.source,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    return {"id": project_id, "name": data.name, "source": data.source}

@app.get("/projects")
def list_projects(limit: int = 20, user=Depends(current_user)):
    db = get_db()
    base = db.collection("projects").where("uid", "==", user["uid"])
    try:
        q = base.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        items = [doc.to_dict() for doc in q.stream()]
        return {"items": items}
    except Exception:
        docs = [doc.to_dict() for doc in base.stream()]
        docs.sort(key=lambda d: _ts_val(d.get("createdAt")), reverse=True)
        return {"items": docs[:limit]}

@app.post("/projects/{project_id}/upload")
async def upload_project_code(project_id: str, file: UploadFile = File(...), user=Depends(current_user)):
    if file.content_type not in ("application/zip", "application/x-zip-compressed", "application/octet-stream"):
        raise HTTPException(400, "Upload a .zip of your project.")
    data = await file.read()
    dest = project_path(project_id)
    extract_zip_to(data, dest)
    return {"ok": True, "projectId": project_id, "path": dest}

@app.post("/projects/github")
def import_github_repo(data: GithubImport, background: BackgroundTasks, user=Depends(current_user)):
    db = get_db()

    # 1) create project
    pid = str(uuid4())
    name = data.name or data.repoUrl.split("/")[-1].replace(".git", "")
    project = {
        "id": pid,
        "uid": user["uid"],
        "name": name,
        "source": "github",
        "repoUrl": data.repoUrl,
        "branch": data.branch or "main",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    db.collection("projects").document(pid).set(project)

    # 2) clone
    dest = project_path(pid)
    try:
        shallow_clone(data.repoUrl, dest, project["branch"], token=GITHUB_TOKEN or None)
    except Exception as e:
        db.collection("projects").document(pid).set(
            {"error": str(e), "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True
        )
        raise HTTPException(status_code=400, detail=f"Clone failed: {e}")

    # 3) commit sha
    sha = get_head_sha(dest)
    db.collection("projects").document(pid).set(
        {"commit": sha, "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True
    )

    # 4) create job and run analysis
    jid = str(uuid4())
    job = {
        "id": jid,
        "uid": user["uid"],
        "projectId": pid,
        "status": "pending",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    db.collection("jobs").document(jid).set(job)
    background.add_task(process_job, jid, pid, user["uid"])

    return {"projectId": pid, "jobId": jid, "status": "pending"}


# -------------------------------
# Jobs
# -------------------------------

@app.post("/jobs")
def create_job(data: JobCreate, background: BackgroundTasks, user=Depends(current_user)):
    db = get_db()
    job_id = str(uuid4())
    db.collection("jobs").document(job_id).set({
        "id": job_id,
        "projectId": data.projectId,
        "uid": user["uid"],
        "status": "pending",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    background.add_task(process_job, job_id, data.projectId, user["uid"])
    return {"id": job_id, "status": "pending"}

@app.get("/jobs")
def list_jobs(projectId: Optional[str] = None, limit: int = 20, user=Depends(current_user)):
    db = get_db()
    base = db.collection("jobs").where("uid", "==", user["uid"])
    if projectId:
        base = base.where("projectId", "==", projectId)
    try:
        q = base.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        items = [doc.to_dict() for doc in q.stream()]
        return {"items": items}
    except Exception:
        docs = [doc.to_dict() for doc in base.stream()]
        docs.sort(key=lambda d: _ts_val(d.get("createdAt")), reverse=True)
        return {"items": docs[:limit]}

@app.get("/jobs/{job_id}")
def get_job(job_id: str, user=Depends(current_user)):
    db = get_db()
    doc = db.collection("jobs").document(job_id).get()
    if not doc.exists:
        raise HTTPException(404, "job not found")
    j = doc.to_dict()
    if j.get("uid") != user["uid"]:
        raise HTTPException(403, "forbidden")
    return j


def process_job(job_id: str, project_id: str, uid: str):
    """
    Background job executor:
    - runs static tools
    - generates AI review
    - builds normalized vpoints
    - stores everything on the job doc
    """
    db = get_db()
    jobs = db.collection("jobs").document(job_id)
    jobs.set({"status": "running", "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)

    try:
        path = project_path(project_id)
        results = run_all(path)  # static analysis per your existing implementation

        # AI summary
        try:
            ai = generate_review(results)
        except Exception as e:
            ai = {"error": f"AI summarization failed: {e}"}

        # Normalized findings for UI highlighting
        vpoints = []
        try:
            vpoints = build_vpoints(results)
        except Exception as _:
            vpoints = []

        # Persist
        out_results = {**results, "ai": ai, "vpoints": vpoints, "projectId": project_id}
        jobs.set({
            "status": "done",
            "results": out_results,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)

    except Exception as e:
        jobs.set({
            "status": "error",
            "error": str(e),
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)


# -------------------------------
# File content (for highlighting)
# -------------------------------

@app.get("/projects/{project_id}/file")
def get_project_file(project_id: str, path: str = Query(...), user=Depends(current_user)):
    # permissions: user owns the project
    db = get_db()
    proj = db.collection("projects").document(project_id).get().to_dict() or {}
    if not proj or proj.get("uid") != user["uid"]:
        raise HTTPException(status_code=404, detail="project not found")

    # resolve path safely inside the project directory
    root = Path(project_path(project_id)).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"cannot read file: {e}")

    # naive language hint
    lang = "python" if target.suffix == ".py" else "text"
    return {"path": path, "language": lang, "content": content}
