import hashlib
import secrets
from typing import Optional, Dict, Any
from fastapi import HTTPException, Header
from backend.database import (
    get_user_by_username,
    get_user_by_id,
    create_user,
    save_auth_token,
    get_auth_token_user_id,
    delete_auth_token,
)

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    # PBKDF2 HMAC with SHA-256 and 100,000 iterations
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return pwd_hash, salt

def verify_password(password: str, password_hash: str, salt: str) -> bool:
    check_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(check_hash, password_hash)

def generate_session_token(user_id: int) -> str:
    # Tokens are opaque random strings. They are only valid if they exist in
    # the auth_tokens table, so they cannot be forged from a known user id.
    token = secrets.token_urlsafe(32)
    save_auth_token(token, user_id)
    return token

def _extract_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:]
    return token.strip()

def register_user(username: str, password: str, email: str = "") -> Dict[str, Any]:
    username = username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    existing = get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists. Please login or choose another.")

    pwd_hash, salt = hash_password(password)
    user_id = create_user(username=username, email=email, password_hash=pwd_hash, salt=salt)
    token = generate_session_token(user_id)
    return {
        "user": {"id": user_id, "username": username, "email": email},
        "token": token
    }

def authenticate_user(username: str, password: str) -> Dict[str, Any]:
    username = username.strip()
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_password(password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = generate_session_token(user["id"])
    return {
        "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
        "token": token
    }

def revoke_token(authorization: Optional[str]):
    token = _extract_token(authorization)
    if token:
        delete_auth_token(token)

async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token missing")

    user_id = get_auth_token_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please login again.")

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User account not found")

    return {"id": user["id"], "username": user["username"], "email": user["email"]}
