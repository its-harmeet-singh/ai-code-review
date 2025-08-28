import os, json
from typing import Any, Dict, List
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # fast/cheap; you can swap later

def _summarize_for_prompt(results: Dict[str, Any]) -> str:
    """Make a compact prompt payload to keep tokens small."""
    data = {}

    # pylint (keep only top 30 items)
    py = results.get("pylint", {})
    items = py.get("items", [])[:30]
    data["pylint"] = [{"path": i.get("path"), "msg": i.get("message"),
                       "symbol": i.get("symbol"), "line": i.get("line")}
                      for i in items]
    if py.get("score") is not None:
        data["pylint_score"] = py["score"]

    # bandit (keep findings only; top 30)
    bd = results.get("bandit", {}).get("report", {})
    findings = (bd.get("results") or [])[:30]
    data["bandit"] = [{"filename": f.get("filename"),
                       "test_id": f.get("test_id"),
                       "issue_text": f.get("issue_text"),
                       "severity": f.get("issue_severity"),
                       "confidence": f.get("issue_confidence"),
                       "line": f.get("line_number")}
                      for f in findings]

    # radon complexity & MI (summarize grades)
    rd = results.get("radon", {})
    mi = rd.get("mi", {}).get("data", {})
    cc = rd.get("cc", {}).get("data", {})
    data["radon_mi"] = {k: v.get("mi") for k, v in mi.items()}
    # For cc, keep per-function ranks only
    cc_flat: List[Dict[str, Any]] = []
    for file, funcs in (cc or {}).items():
        for f in funcs:
            cc_flat.append({"file": file, "name": f.get("name"),
                            "complexity": f.get("complexity"), "rank": f.get("rank")})
    data["radon_cc"] = cc_flat[:50]

    return json.dumps(data, ensure_ascii=False)

def generate_review(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns dict:
    {
      "summary": "...",
      "checklist": [ {"title": "...","why":"...","how":"...","severity":"low|med|high"} ],
      "top_wins": ["...","..."]
    }
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    compact = _summarize_for_prompt(results)

    system = (
        "You are a senior staff engineer doing a code review. "
        "You receive outputs from pylint (style), bandit (security), and radon (complexity). "
        "Write concise, actionable guidance. Prefer specific file/line refs if available. "
        "Do NOT invent findings that aren't in the provided data."
    )
    user = (
        "Static-analysis findings (JSON):\n"
        f"{compact}\n\n"
        "Task: 1) Brief summary (2–4 sentences). "
        "2) A prioritized checklist (max 8 items) with fields: title, why, how, severity. "
        "3) 3 quick wins (bullet points). "
        "Return strict JSON with keys: summary, checklist, top_wins."
    )

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except Exception:
        return {"summary": content, "checklist": [], "top_wins": []}
