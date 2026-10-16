"""
Structured extraction for the AngularJS pages whose content is filled in by
XHR after load (Faculty Directory and Training & Placements).

Why this exists: the old crawler fetched the raw Angular template, which only
contains placeholders like `{{faculty.name}}`, so the index held no real names,
departments, phones or emails. This module renders the page in a headless
browser, waits for Angular to finish binding, rejects output that still holds
placeholders, and turns HTML tables into clean records.
"""
import html as html_lib
import json
import logging
import os
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

logger = logging.getLogger("crawler.dynamic")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEBUG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "debug",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?(?:0?\d{10}|\d{3,5}[\s-]\d{5,8})")
# Only raw Angular bindings mean "not rendered". Words like contact_phone /
# location_on are Material icon names that also appear on correctly rendered
# pages, so they must not count (they made every real faculty row get rejected).
PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}")


def has_unrendered_placeholders(text: str) -> bool:
    return bool(PLACEHOLDER_RE.search(text or ""))


# ---------------------------------------------------------------------------
# HTML table parsing
# ---------------------------------------------------------------------------
class _TableParser(HTMLParser):
    """Collects every top-level <table> as a list of rows (lists of cell text)."""

    def __init__(self):
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._depth = 0
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style"):
            self._skip += 1
        elif t == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif t == "tr" and self._depth:
            self._row = []
        elif t in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif t in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif t == "tr" and self._row is not None:
            if any(self._row) and self._depth == 1:
                self.tables[-1].append(self._row)
            self._row = None
        elif t == "table" and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if not self._skip and self._cell is not None:
            self._cell.append(data)


def extract_tables(html: str) -> List[List[List[str]]]:
    parser = _TableParser()
    parser.feed(html)
    return [t for t in parser.tables if len(t) >= 2]


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z]+", "_", s.lower()).strip("_")


def rows_to_records(table: List[List[str]]) -> List[Dict[str, str]]:
    """First non-empty row is treated as the header. Keys are normalised."""
    header = [_norm_key(h) or f"col{i}" for i, h in enumerate(table[0])]
    records = []
    for row in table[1:]:
        if not any(row):
            continue
        rec = {}
        for i, key in enumerate(header):
            rec[key] = row[i] if i < len(row) else ""
        records.append(rec)
    return records


def _pick(rec: Dict[str, str], *needles: str) -> str:
    for key, val in rec.items():
        if any(n in key for n in needles) and val:
            return val
    return ""


def canonical_faculty(rec: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Map a raw table row onto name / department / designation / phone / email."""
    row_text = " ".join(rec.values())
    email = _pick(rec, "mail") or (EMAIL_RE.search(row_text).group(0) if EMAIL_RE.search(row_text) else "")
    phone = _pick(rec, "phone", "mobile", "contact", "tel") or ""
    if not phone:
        m = PHONE_RE.search(row_text)
        phone = m.group(0).strip() if m else ""
    name = _pick(rec, "name") or next(iter(rec.values()), "")
    if not name or has_unrendered_placeholders(row_text):
        return None
    return {
        "name": name,
        "department": _pick(rec, "dept", "department", "branch", "area"),
        "designation": _pick(rec, "desig", "position", "title", "post", "role"),
        "phone": phone,
        "email": email,
    }


def canonical_placement_row(rec: Dict[str, str]) -> str:
    """Placement rows vary by year, so keep every non-empty column as 'label: value'."""
    return "; ".join(f"{k.replace('_', ' ').strip()}: {v}" for k, v in rec.items() if v)


# ---------------------------------------------------------------------------
# Headless rendering
# ---------------------------------------------------------------------------
def render_dynamic_page(browser, url: str, timeout_ms: int = 30000) -> Optional[Dict[str, Any]]:
    """
    Loads the SPA route in a real browser, waits for Angular to replace the
    `{{ }}` placeholders, and returns the rendered HTML plus any JSON/XHR
    responses (kept for diagnostics and for finding the data API).
    """
    page = browser.new_page(user_agent=USER_AGENT)
    xhr_log: List[Dict[str, Any]] = []

    def _on_response(resp):
        try:
            if resp.request.resource_type in ("xhr", "fetch"):
                xhr_log.append({"url": resp.url, "status": resp.status})
        except Exception:
            pass

    page.on("response", _on_response)
    try:
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            page.goto(url, wait_until="load", timeout=timeout_ms)

        try:
            # Angular is done when no raw "{{" survives in the visible text.
            page.wait_for_function(
                "() => !document.body || !document.body.innerText.includes('{{')",
                timeout=15000,
            )
        except Exception:
            logger.warning(f"{url}: placeholders still visible after waiting; using what rendered.")
        page.wait_for_timeout(1500)
        return {"html": page.content(), "xhr": xhr_log}
    except Exception as e:
        logger.warning(f"Dynamic render failed for {url}: {e}")
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def save_debug_dump(name: str, rendered: Dict[str, Any]) -> None:
    """Writes the rendered DOM and XHR list to data/debug/ for inspection."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(rendered["html"])
        with open(os.path.join(DEBUG_DIR, f"{name}_xhr.json"), "w", encoding="utf-8") as f:
            json.dump(rendered["xhr"], f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write debug dump {name}: {e}")


# ---------------------------------------------------------------------------
# Public entry points used by the crawler
# ---------------------------------------------------------------------------
FACULTY_CARD_RE = re.compile(r'<div[^>]*ng-repeat="faculty in faculties[^"]*"[^>]*>')
CARD_END_MARKER = "<!-- end ngRepeat: faculty in faculties"
ICON_RE = re.compile(r"<i[^>]*material-icons[^>]*>.*?</i>", re.S)


def _fragment_text(fragment: str) -> str:
    fragment = ICON_RE.sub(" ", fragment)
    fragment = re.sub(r"<br\s*/?>", " / ", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(fragment)).strip(" /")


def _deobfuscate_email(text: str) -> str:
    """The site writes emails as 'name at iiitkottayam dot ac.in'."""
    m = EMAIL_RE.search(text)
    if m:
        return m.group(0)
    text = re.sub(r"\s+at\s+", "@", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s+dot\s+", ".", text, flags=re.IGNORECASE)
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""


def extract_faculty_cards(html: str) -> List[Dict[str, str]]:
    """
    The live Faculty page renders one card per person (no <table>):
    <h5> name, sub-head rows for role/designation and a bold qualification,
    <li> research areas, and contact "chips" for phone, room and email.
    """
    records: List[Dict[str, str]] = []
    for part in FACULTY_CARD_RE.split(html)[1:]:
        end = part.find(CARD_END_MARKER)
        if end != -1:
            part = part[:end]
        part = re.sub(r"<!--.*?-->", "", part, flags=re.S)

        m = re.search(r"<h5[^>]*>(.*?)</h5>", part, re.S)
        name = _fragment_text(m.group(1)) if m else ""
        if not name or has_unrendered_placeholders(name):
            continue

        designation, qualification = [], ""
        for sub in re.findall(r'<div class="custom-card-sub-head[^"]*"[^>]*>(.*?)</div>', part, re.S):
            text = _fragment_text(sub)
            if not text:
                continue
            if re.search(r"<b[\s>]", sub):
                qualification = text
            else:
                designation.append(text)

        areas = [_fragment_text(a) for a in re.findall(
            r'<li[^>]*ng-repeat="area in faculty\.area"[^>]*>(.*?)</li>', part, re.S)]

        contact = {"phone": "", "room": "", "email": ""}
        for field, cls, body in re.findall(
                r'<div ng-show="faculty\.contact\.(phone|room|email)" class="([^"]*)"[^>]*>(.*?)</div>', part, re.S):
            if "ng-hide" in cls:
                continue
            text = _fragment_text(body)
            contact[field] = _deobfuscate_email(text) if field == "email" else text
        contact["room"] = re.sub(r"^Room No:\s*", "", contact["room"])

        records.append({
            "name": name,
            "department": "",
            "designation": " / ".join(designation),
            "phone": contact["phone"],
            "email": contact["email"],
            "room": contact["room"],
            "areas": ", ".join(a for a in areas if a),
            "qualification": qualification,
        })
    return records


def extract_faculty(html: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for table in extract_tables(html):
        for raw in rows_to_records(table):
            fac = canonical_faculty(raw)
            if fac:
                records.append(fac)
    if not records:
        records = extract_faculty_cards(html)
    # de-duplicate on name+department (tables sometimes repeat on mobile layouts)
    seen, unique = set(), []
    for r in records:
        key = (r["name"].lower(), r["department"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def extract_placement_rows(html: str) -> List[str]:
    lines: List[str] = []
    for table in extract_tables(html):
        for raw in rows_to_records(table):
            line = canonical_placement_row(raw)
            if line and not has_unrendered_placeholders(line):
                lines.append(line)
    return lines
