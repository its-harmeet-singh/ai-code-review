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
from app.analysis.ai_review import generate_review
from firebase_admin import firestore
from app.deps.firebase import verify_id_token, get_db
from app.utils.fs import project_path, extract_zip_to
from app.analysis.static_tools import run_all
from app.utils.git import shallow_clone, get_head_sha


class ProjectCreate(BaseModel):
    name: str
    source: str   # "upload" | "github" | "git"

class JobCreate(BaseModel):
    projectId: str

class GithubImport(BaseModel):
    repoUrl: str
    branch: str | None = "main"
    # optional: name override
    name: str | None = None

app = FastAPI(title="AI Code Review API", version="0.3.0")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    load_dotenv(env_path)

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

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

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
    return {"uid": uid, "email": user.get("email"), "name": user.get("name"), "provider": user.get("firebase", {}).get("sign_in_provider")}

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
    })
    return {"id": project_id, "name": data.name, "source": data.source}

@app.get("/projects")
def list_projects(limit: int = 20, user=Depends(current_user)):
    db = get_db()
    base = db.collection("projects").where("uid", "==", user["uid"])

    # Try to use Firestore order_by first (fast path)
    try:
        q = base.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        items = [doc.to_dict() for doc in q.stream()]
        return {"items": items}
    except Exception as e:
        # Fallback: no order_by; sort in Python to avoid 500s
        docs = [doc.to_dict() for doc in base.stream()]
        docs.sort(key=lambda d: _ts_val(d.get("createdAt")), reverse=True)
        return {"items": docs[:limit]}

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
    # enqueue background task
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
    db = get_db()
    jobs = db.collection("jobs").document(job_id)
    jobs.set({"status": "running", "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
    try:
        path = project_path(project_id)
        results = run_all(path)

        # AI summary
        ai = {}
        try:
            ai = generate_review(results)
        except Exception as e:
            ai = {"error": f"AI summarization failed: {e}"}

        jobs.set({
            "status": "done",
            "results": {**results, "ai": ai},
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)
    except Exception as e:
        jobs.set({
            "status": "error",
            "error": str(e),
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)

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
    dest = project_path(pid)  # existing helper, e.g. storage/projects/<pid>
    try:
        shallow_clone(data.repoUrl, dest, project["branch"], token=GITHUB_TOKEN or None)
    except Exception as e:
        # mark project error and bubble up
        db.collection("projects").document(pid).set({"error": str(e), "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
        raise HTTPException(status_code=400, detail=f"Clone failed: {e}")

    # 3) optional: store commit
    sha = get_head_sha(dest)
    db.collection("projects").document(pid).set({"commit": sha, "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)

    # 4) create job and run analysis (same as upload flow)
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