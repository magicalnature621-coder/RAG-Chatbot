import os
import uuid
import threading
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()  # so an API key placed in a .env file actually reaches os.environ

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.database import (
    init_db,
    get_user_sessions,
    get_session_by_id,
    create_session,
    update_session_title,
    delete_session,
    get_session_messages,
    add_message,
    get_all_crawled_pages,
    get_setting,
    set_setting
)
from backend.auth import register_user, authenticate_user, get_current_user, revoke_token
from backend.rag.pipeline import get_rag_pipeline
from backend.crawler.crawler import CollegeCrawler
from backend.crawler.scheduler import CrawlerScheduler

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

DEFAULT_SITE_URL = "https://iiitkottayam.ac.in/#!/home"
VALID_PROVIDERS = {"local", "groq", "gemini", "openai"}

# Tables must exist before any request (or test client) touches the database.
init_db()

# Global instances
rag_pipeline = get_rag_pipeline()
crawler = CollegeCrawler(vector_store=rag_pipeline.vector_store)
scheduler = CrawlerScheduler(crawler=crawler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Start periodic scheduler
    scheduler.start(interval_hours=6.0)

    # Check if vector store is empty, trigger initial crawl in background
    stats = rag_pipeline.vector_store.get_stats()
    if stats["total_chunks"] == 0:
        print("Vector store is empty. Triggering initial crawl for IIIT Kottayam in background...")
        threading.Thread(
            target=crawler.run_sync,
            kwargs={"target_url": DEFAULT_SITE_URL},
            daemon=True
        ).start()
    yield
    scheduler.stop()

app = FastAPI(title="College RAG Chatbot API", version="1.0.0", lifespan=lifespan)

# Auth uses a bearer token header, not cookies, so credentials are not needed
# (and "*" origins with credentials is rejected by browsers anyway).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request Models ---
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = ""

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New Conversation"

class SendMessageRequest(BaseModel):
    content: str

class SyncRequest(BaseModel):
    target_url: Optional[str] = None

class ConfigRequest(BaseModel):
    llm_provider: Optional[str] = None
    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    college_website_url: Optional[str] = None

# --- Auth Routes ---
@app.post("/api/auth/register")
def register(req: RegisterRequest):
    return register_user(req.username, req.password, req.email or "")

@app.post("/api/auth/login")
def login(req: LoginRequest):
    return authenticate_user(req.username, req.password)

@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    revoke_token(authorization)
    return {"status": "logged_out"}

@app.get("/api/auth/me")
def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return {"user": user}

# --- Chat Session Routes ---
@app.get("/api/sessions")
def list_sessions(user: Dict[str, Any] = Depends(get_current_user)):
    sessions = get_user_sessions(user["id"])
    return {"sessions": sessions}

@app.post("/api/sessions")
def new_session(req: CreateSessionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    session_id = str(uuid.uuid4())
    session = create_session(session_id, user["id"], req.title or "New Conversation")
    return {"session": session}

@app.get("/api/sessions/{session_id}")
def get_session_history(session_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    session = get_session_by_id(session_id)
    if not session or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = get_session_messages(session_id)
    return {"session": session, "messages": messages}

@app.delete("/api/sessions/{session_id}")
def remove_session(session_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    success = delete_session(session_id, user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}

@app.post("/api/sessions/{session_id}/message")
def post_message(
    session_id: str,
    req: SendMessageRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    session = get_session_by_id(session_id)
    if not session or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    # 1. Fetch previous messages for conversation history
    prev_messages = get_session_messages(session_id)
    history = [{"role": m["role"], "content": m["content"]} for m in prev_messages]

    # 2. Save user message to database
    user_msg_id = str(uuid.uuid4())
    add_message(user_msg_id, session_id, role="user", content=content)

    # 3. Update session title if first user message
    if len(prev_messages) == 0 or session["title"] in ("New Conversation", "New Chat"):
        new_title = " ".join(content.split()[:6])
        if len(content.split()) > 6:
            new_title += "..."
        update_session_title(session_id, new_title)

    # 4. Run RAG Pipeline
    result = rag_pipeline.query(content, history=history)

    # 5. Save assistant message to database
    bot_msg_id = str(uuid.uuid4())
    bot_msg = add_message(
        bot_msg_id,
        session_id,
        role="assistant",
        content=result["answer"],
        sources=result["sources"]
    )

    return {
        "message": bot_msg,
        "sources": result["sources"],
        "provider": result["provider"]
    }

# --- Crawler & Sync Routes ---
@app.post("/api/crawler/sync")
def trigger_sync(req: Optional[SyncRequest] = None, user: Dict[str, Any] = Depends(get_current_user)):
    target_url = req.target_url if req else None
    if target_url and not target_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="target_url must start with http:// or https://")
    if crawler.is_running:
        return {"status": "in_progress", "message": "Crawler is already running"}

    def _async_sync():
        crawler.run_sync(target_url=target_url)

    threading.Thread(target=_async_sync, daemon=True).start()
    return {"status": "started", "message": "Crawler started in background"}

@app.get("/api/crawler/status")
def get_crawler_status():
    stats = rag_pipeline.vector_store.get_stats()
    all_pages = get_all_crawled_pages()
    last_sync = get_setting("last_sync_time")
    target_url = get_setting("college_website_url", DEFAULT_SITE_URL)
    
    return {
        "is_running": crawler.is_running,
        "total_chunks": stats["total_chunks"],
        "total_pages": len(all_pages),
        "last_sync_time": last_sync,
        "target_url": target_url
    }

@app.get("/api/crawler/pages")
def list_crawled_pages():
    pages = get_all_crawled_pages()
    return {"pages": pages}

# --- Configuration Routes ---
@app.get("/api/config")
def get_config():
    provider = rag_pipeline.llm.get_active_provider()
    target_url = get_setting("college_website_url", DEFAULT_SITE_URL)
    return {
        "llm_provider": provider,
        "college_website_url": target_url,
        "has_groq_key": bool(get_setting("groq_api_key") or os.environ.get("GROQ_API_KEY")),
        "has_gemini_key": bool(get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY")),
        "has_openai_key": bool(get_setting("openai_api_key") or os.environ.get("OPENAI_API_KEY"))
    }

@app.post("/api/config")
def update_config(req: ConfigRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if req.llm_provider:
        if req.llm_provider not in VALID_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"llm_provider must be one of {sorted(VALID_PROVIDERS)}")
        set_setting("llm_provider", req.llm_provider)
    if req.groq_api_key is not None:
        set_setting("groq_api_key", req.groq_api_key)
    if req.gemini_api_key is not None:
        set_setting("gemini_api_key", req.gemini_api_key)
    if req.openai_api_key is not None:
        set_setting("openai_api_key", req.openai_api_key)
    if req.college_website_url:
        if not req.college_website_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="college_website_url must start with http:// or https://")
        set_setting("college_website_url", req.college_website_url)
    return {"status": "updated"}

# Mount frontend static files
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
