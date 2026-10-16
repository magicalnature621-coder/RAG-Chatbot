"""
Structured records for Faculty and Placements.

Top-k chunk retrieval cannot answer "list all faculty" - the answer is spread
over dozens of rows and only ~4 chunks reach the LLM. So for these two topics
we keep the complete record set in data/structured.json and hand the whole
set to the model (or print it directly in local mode) whenever the question
is about faculty or placements.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

STRUCTURED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "structured.json",
)

FACULTY_URL = "https://iiitkottayam.ac.in/#!/faculty"
PLACEMENT_URL = "https://iiitkottayam.ac.in/#!/placement"

FACULTY_INTENT_RE = re.compile(
    r"\b(faculty|faculties|professor|professors|prof|teacher|teachers|hod|dean|"
    r"director|lecturer|lecturers|email|mail\s*id|department\s*head)\b",
    re.IGNORECASE,
)
PLACEMENT_INTENT_RE = re.compile(
    r"\b(placement|placements|placed|package|packages|ctc|lpa|recruiter|recruiters|"
    r"recruitment|company|companies|internship|internships|salary)\b",
    re.IGNORECASE,
)


def load_structured() -> Dict[str, Any]:
    if not os.path.exists(STRUCTURED_PATH):
        return {"faculty": [], "placement_lines": [], "placement_text": ""}
    try:
        with open(STRUCTURED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"faculty": [], "placement_lines": [], "placement_text": ""}


def save_structured(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STRUCTURED_PATH), exist_ok=True)
    with open(STRUCTURED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def faculty_document(records: List[Dict[str, str]]) -> str:
    """One line per faculty member so the LLM can filter by name, dept or email."""
    lines = [
        "IIIT Kottayam Faculty Directory. Complete list of faculty members with "
        "department, designation, contact phone and email:"
    ]
    for r in records:
        parts = [r.get("name", "")]
        if r.get("department"):
            parts.append(f"Department: {r['department']}")
        if r.get("designation"):
            parts.append(f"Designation: {r['designation']}")
        if r.get("phone"):
            parts.append(f"Phone: {r['phone']}")
        if r.get("email"):
            parts.append(f"Email: {r['email']}")
        lines.append(" | ".join(parts))
    lines.append(f"Total faculty listed: {len(records)}.")
    return "\n".join(lines)


def placement_document(lines: List[str], page_text: str) -> str:
    out = ["IIIT Kottayam Training and Placements. Campus placement details:"]
    out.extend(lines)
    if page_text:
        out.append(page_text)
    return "\n".join(out)


def detect_structured_intent(question: str) -> Optional[str]:
    if FACULTY_INTENT_RE.search(question):
        return "faculty"
    if PLACEMENT_INTENT_RE.search(question):
        return "placement"
    return None


def structured_context_chunk(intent: str) -> Optional[Dict[str, Any]]:
    """Returns one synthetic chunk holding the full dataset for this intent."""
    data = load_structured()
    if intent == "faculty" and data.get("faculty"):
        text = faculty_document(data["faculty"])
        return {
            "chunk_id": "structured_faculty",
            "doc_id": FACULTY_URL,
            "title": "Faculty Directory | IIIT Kottayam",
            "source_url": FACULTY_URL,
            "text": text,
            "score": 1000.0,
            "bm25_score": 0.0,
            "cosine_score": 0.0,
        }
    if intent == "placement" and (data.get("placement_lines") or data.get("placement_text")):
        text = placement_document(data.get("placement_lines", []), data.get("placement_text", ""))
        return {
            "chunk_id": "structured_placement",
            "doc_id": PLACEMENT_URL,
            "title": "Training & Placements | IIIT Kottayam",
            "source_url": PLACEMENT_URL,
            "text": text,
            "score": 1000.0,
            "bm25_score": 0.0,
            "cosine_score": 0.0,
        }
    return None


def faculty_markdown_table(records: List[Dict[str, str]]) -> str:
    """Deterministic answer for local (no-LLM) mode: the full list, no guessing."""
    rows = ["| # | Name | Department | Designation | Phone | Email |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(records, 1):
        rows.append(
            f"| {i} | {r.get('name','')} | {r.get('department','')} | {r.get('designation','')} "
            f"| {r.get('phone','') or '-'} | {r.get('email','') or '-'} |"
        )
    return "\n".join(rows)
