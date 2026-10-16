import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
# Overridable so tests (or a deployment) can point at a different database file.
DB_PATH = os.environ.get("COLLEGE_RAG_DB_PATH") or os.path.join(DB_DIR, "college_rag.db")

def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    # 2. Chat sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # 3. Chat messages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sources_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """)
    
    # 4. Crawled pages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS crawled_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        chunk_count INTEGER DEFAULT 0,
        last_crawled_at TEXT NOT NULL,
        status TEXT NOT NULL
    )
    """)
    
    # 5. Auth tokens table (login sessions survive restarts and can be revoked)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 6. Settings table (for dynamic configuration like active website URL, LLM model, API key)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

# --- User Operations ---
def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username: str, email: str, password_hash: str, salt: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, email, password_hash, salt, _now())
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return user_id

# --- Auth Token Operations ---
def save_auth_token(token: str, user_id: int):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, _now())
    )
    conn.commit()
    conn.close()

def get_auth_token_user_id(token: str) -> Optional[int]:
    conn = get_db_connection()
    row = conn.execute("SELECT user_id FROM auth_tokens WHERE token = ?", (token,)).fetchone()
    conn.close()
    return row["user_id"] if row else None

def delete_auth_token(token: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()

# --- Session Operations ---
def get_user_sessions(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC", 
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_session(session_id: str, user_id: int, title: str) -> Dict[str, Any]:
    now = _now()
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, title, now, now)
    )
    conn.commit()
    conn.close()
    return {"id": session_id, "user_id": user_id, "title": title, "created_at": now, "updated_at": now}

def update_session_title(session_id: str, title: str):
    now = _now()
    conn = get_db_connection()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, session_id)
    )
    conn.commit()
    conn.close()

def delete_session(session_id: str, user_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ownership check first, so one user can never wipe another user's messages.
    cursor.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    affected = cursor.rowcount > 0
    if affected:
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    return affected

# --- Message Operations ---
def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC", 
        (session_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("sources_json"):
            try:
                d["sources"] = json.loads(d["sources_json"])
            except Exception:
                d["sources"] = []
        else:
            d["sources"] = []
        result.append(d)
    return result

def add_message(message_id: str, session_id: str, role: str, content: str, sources: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    now = _now()
    sources_json = json.dumps(sources) if sources else None
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, sources_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, session_id, role, content, sources_json, now)
    )
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    conn.commit()
    conn.close()
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": now
    }

# --- Crawled Page Operations ---
def get_all_crawled_pages() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM crawled_pages ORDER BY last_crawled_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_crawled_page(url: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM crawled_pages WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None

def upsert_crawled_page(url: str, title: str, content_hash: str, chunk_count: int, status: str):
    now = _now()
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO crawled_pages (url, title, content_hash, chunk_count, last_crawled_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title = excluded.title,
            content_hash = excluded.content_hash,
            chunk_count = excluded.chunk_count,
            last_crawled_at = excluded.last_crawled_at,
            status = excluded.status
    """, (url, title, content_hash, chunk_count, now, status))
    conn.commit()
    conn.close()

# --- Setting Operations ---
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
