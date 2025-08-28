import os, shutil, subprocess
from typing import Optional

def _auth_url(repo_url: str, token: Optional[str]) -> str:
    # Use a token for private HTTPS repos if provided
    if token and repo_url.startswith("https://"):
        # Avoid printing token anywhere!
        return repo_url.replace("https://", f"https://{token}@", 1)
    return repo_url

def shallow_clone(repo_url: str, dest: str, branch: str = "main", token: Optional[str] = None):
    # Clean destination
    if os.path.exists(dest):
        shutil.rmtree(dest)

    auth = _auth_url(repo_url, token)
    cmd = [
        "git", "clone",
        "--depth", "1",
        "--single-branch",
        "--branch", branch,
        auth, dest,
    ]
    subprocess.run(cmd, check=True)

def get_head_sha(repo_path: str) -> str:
    try:
        out = subprocess.check_output(["git", "-C", repo_path, "rev-parse", "HEAD"])
        return out.decode().strip()
    except Exception:
        return ""
