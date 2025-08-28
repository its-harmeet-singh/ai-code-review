import os, zipfile, io, shutil, subprocess, json, shlex
from typing import Dict, Any, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STORAGE_DIR = os.path.join(ROOT, "storage", "projects")

def project_path(project_id: str) -> str:
    path = os.path.join(STORAGE_DIR, project_id)
    os.makedirs(path, exist_ok=True)
    return path

def extract_zip_to(zip_bytes: bytes, dest_dir: str) -> None:
    # clean dest first for idempotency
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(dest_dir)

def run_cmd(cmd: str, cwd: str | None = None, timeout: int = 120) -> Tuple[int, str, str]:
    """Run a shell command, return (code, stdout, stderr)."""
    proc = subprocess.Popen(
        shlex.split(cmd),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return 124, "", "timeout"
    return proc.returncode, out, err

def parse_json_safe(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s.strip()}
