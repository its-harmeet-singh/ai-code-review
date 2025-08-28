import os
from typing import Dict, Any
from .types import AnalysisResult
from app.utils.fs import run_cmd, parse_json_safe

def run_pylint(path: str) -> Dict[str, Any]:
    # JSON output
    code, out, err = run_cmd(f"python -m pylint --output-format=json {path}", cwd=path, timeout=180)
    data = parse_json_safe(out) if out else []
    score = None
    # Try to parse score from stderr summary if present
    if "rated at" in err:
        # e.g., "Your code has been rated at 8.50/10"
        try:
            score = float(err.split("rated at")[1].split("/")[0].strip())
        except Exception:
            pass
    return {"exitCode": code, "items": data, "score": score, "stderr": err.strip()[:2000]}

def run_bandit(path: str) -> Dict[str, Any]:
    code, out, err = run_cmd(f"python -m bandit -r -f json .", cwd=path, timeout=180)
    data = parse_json_safe(out) if out else {}
    return {"exitCode": code, "report": data, "stderr": err.strip()[:2000]}

def run_radon(path: str) -> Dict[str, Any]:
    # Cyclomatic Complexity & Maintainability Index
    cc_code, cc_out, cc_err = run_cmd("radon cc -s -j .", cwd=path, timeout=180)
    mi_code, mi_out, mi_err = run_cmd("radon mi -j .", cwd=path, timeout=180)
    cc = parse_json_safe(cc_out) if cc_out else {}
    mi = parse_json_safe(mi_out) if mi_out else {}
    return {
        "cc": {"exitCode": cc_code, "data": cc, "stderr": cc_err.strip()[:2000]},
        "mi": {"exitCode": mi_code, "data": mi, "stderr": mi_err.strip()[:2000]},
    }

def run_all(path: str) -> AnalysisResult:
    return {
        "pylint": run_pylint(path),
        "bandit": run_bandit(path),
        "radon": run_radon(path),
    }
