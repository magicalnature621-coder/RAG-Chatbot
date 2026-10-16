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


FACULTY_DETAIL_FIELDS = [
    ("department", "Department"),
    ("designation", "Designation"),
    ("areas", "Research areas"),
    ("qualification", "Background"),
    ("phone", "Phone"),
    ("email", "Email"),
    ("room", "Room"),
]

# Words too common in faculty questions to identify a specific person or topic.
_FACULTY_QUERY_STOPWORDS = {
    "faculty", "faculties", "professor", "professors", "prof", "teacher", "teachers",
    "list", "all", "who", "what", "which", "the", "and", "are", "about", "tell",
    "give", "show", "email", "mail", "phone", "contact", "number", "details",
    "iiit", "kottayam", "college", "department", "dept", "with", "does", "from",
    "their", "them", "there", "teaches", "works", "work", "research", "area", "areas",
}


def _faculty_line(r: Dict[str, str], detailed: bool) -> str:
    fields = FACULTY_DETAIL_FIELDS if detailed else [("designation", "Designation"), ("email", "Email")]
    parts = [r.get("name", "")]
    for key, label in fields:
        if r.get(key):
            parts.append(f"{label}: {r[key]}")
    return " | ".join(parts)


def faculty_document(records: List[Dict[str, str]], detailed: bool = True) -> str:
    """One line per faculty member so the LLM can filter by name, area or email."""
    lines = ["IIIT Kottayam Faculty Directory. Complete list of faculty members:"]
    lines.extend(_faculty_line(r, detailed) for r in records)
    lines.append(f"Total faculty listed: {len(records)}.")
    return "\n".join(lines)


def match_faculty(records: List[Dict[str, str]], question: str) -> List[Dict[str, str]]:
    """Faculty whose name, designation or research areas mention a word from the question."""
    words = [w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in _FACULTY_QUERY_STOPWORDS]
    if not words:
        return []
    matched = []
    for r in records:
        haystack = " ".join(r.get(k, "") for k in ("name", "designation", "areas", "department")).lower()
        if any(re.search(rf"\b{re.escape(w)}", haystack) for w in words):
            matched.append(r)
    return matched


def faculty_context_document(records: List[Dict[str, str]], question: str) -> str:
    """
    Context for the LLM. Sending every field for all faculty would blow past
    small rate limits (e.g. Groq's free tier), so: full details for the people
    the question is about, otherwise a compact name/designation/email list.
    """
    matched = match_faculty(records, question)
    if matched and len(matched) <= 40:
        lines = [
            f"IIIT Kottayam Faculty Directory ({len(records)} members in total). "
            f"Faculty matching the question, with full details:"
        ]
        lines.extend(_faculty_line(r, detailed=True) for r in matched)
        return "\n".join(lines)
    return faculty_document(records, detailed=False)


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


def structured_context_chunk(intent: str, question: str = "") -> Optional[Dict[str, Any]]:
    """Returns one synthetic chunk holding the dataset for this intent."""
    data = load_structured()
    if intent == "faculty" and data.get("faculty"):
        text = faculty_context_document(data["faculty"], question)
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
    def cell(value: str) -> str:
        return (value or "-").replace("|", "/")

    rows = ["| # | Name | Designation | Phone | Email | Room |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(records, 1):
        rows.append(
            f"| {i} | {cell(r.get('name'))} | {cell(r.get('designation'))} "
            f"| {cell(r.get('phone'))} | {cell(r.get('email'))} | {cell(r.get('room'))} |"
        )
    return "\n".join(rows)
