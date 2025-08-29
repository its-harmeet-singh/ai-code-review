from typing import Dict, Any, List

# Normalized finding:
# {
#   "tool": "pylint" | "bandit" | "radon-cc",
#   "path": "relative/path.py",
#   "line": 12,              # 1-based
#   "endLine": 12,           # optional
#   "col": 1,                # optional (1-based)
#   "endCol": None,
#   "severity": "low|medium|high",
#   "code": "C0116",         # tool-specific id where available
#   "message": "Missing function docstring"
# }

def _sev_from_bandit(level: str) -> str:
    m = (level or "").lower()
    if m in ("high",): return "high"
    if m in ("medium", "med"): return "medium"
    return "low"

def _sev_from_pylint(type_: str) -> str:
    # pylint types: convention, refactor, warning, error, fatal
    t = (type_ or "").lower()
    if t in ("fatal", "error"): return "high"
    if t in ("warning", "refactor"): return "medium"
    return "low"

def build_vpoints(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # PYLINT
    for it in (results.get("pylint", {}) or {}).get("items", []) or []:
        out.append({
            "tool": "pylint",
            "path": it.get("path"),
            "line": it.get("line") or 1,
            "endLine": it.get("endLine") or it.get("line") or 1,
            "col": (it.get("column") or 0) + 1,  # pylint returns 0-based sometimes; show 1-based
            "endCol": it.get("endColumn"),
            "severity": _sev_from_pylint(it.get("type")),
            "code": it.get("message-id") or it.get("symbol"),
            "message": it.get("message"),
        })

    # BANDIT
    b_rep = (results.get("bandit", {}) or {}).get("report", {}) or {}
    for it in b_rep.get("results", []) or []:
        out.append({
            "tool": "bandit",
            "path": it.get("filename"),
            "line": it.get("line_number") or 1,
            "endLine": it.get("line_number") or 1,
            "col": 1,
            "endCol": None,
            "severity": _sev_from_bandit(it.get("issue_severity")),
            "code": it.get("test_id"),
            "message": it.get("issue_text"),
        })

    # RADON Cyclomatic Complexity (flag only worse-than-B as a “point”)
    for path, entries in ((results.get("radon", {}) or {}).get("cc", {}) or {}).get("data", {}).items():
        for e in entries or []:
            # ranks: A(best)→F(worst). Mark C or worse as noteworthy.
            rank = (e.get("rank") or "C").upper()
            if rank >= "C":
                out.append({
                    "tool": "radon-cc",
                    "path": path,
                    "line": e.get("lineno") or 1,
                    "endLine": e.get("endline") or e.get("lineno") or 1,
                    "col": 1,
                    "endCol": None,
                    "severity": "medium" if rank in ("C","D") else "high",
                    "code": f"CC-{rank}",
                    "message": f"High cyclomatic complexity ({e.get('complexity')}) rank {rank}",
                })

    return out
