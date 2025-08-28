import os
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from uuid import uuid4
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware

from firebase_admin import firestore
from app.deps.firebase import verify_id_token, get_db
from app.utils.fs import project_path, extract_zip_to
from app.analysis.static_tools import run_all

class ProjectCreate(BaseModel):
    name: str
    source: str   # "upload" | "github" | "git"

class JobCreate(BaseModel):
    projectId: str

app = FastAPI(title="AI Code Review API", version="0.3.0")

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
    """Background worker that runs static tools and updates Firestore."""
    db = get_db()
    jobs = db.collection("jobs").document(job_id)
    # mark running
    jobs.set({"status": "running", "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)

    try:
        path = project_path(project_id)
        results = run_all(path)
        jobs.set({
            "status": "done",
            "results": results,
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