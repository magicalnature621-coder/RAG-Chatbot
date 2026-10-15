import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from backend.main import app

def test_api():
    client = TestClient(app)
    
    # 1. Test Register
    username = "api_test_student"
    password = "secure_password_999"
    
    res = client.post("/api/auth/register", json={"username": username, "password": password})
    if res.status_code == 400: # Already registered
        res = client.post("/api/auth/login", json={"username": username, "password": password})
    
    assert res.status_code == 200, f"Auth failed: {res.text}"
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("1. Auth API: Register & Login OK. Token received.")

    # 2. Test Create Session
    res = client.post("/api/sessions", json={"title": "New Conversation"}, headers=headers)
    assert res.status_code == 200, f"Session create failed: {res.text}"
    session_id = res.json()["session"]["id"]
    print(f"2. Sessions API: Created session {session_id}")

    # 3. Test Post Message (RAG Query)
    res = client.post(
        f"/api/sessions/{session_id}/message",
        json={"content": "What are the B.Tech branches offered at IIIT Kottayam?"},
        headers=headers
    )
    assert res.status_code == 200, f"Post message failed: {res.text}"
    msg_data = res.json()
    print("3. RAG Chat API: Message sent & answered!")
    print(f"   Provider: {msg_data['provider']}")
    print(f"   Sources: {[s['title'] for s in msg_data['sources']]}")
    assert len(msg_data["sources"]) > 0, "Expected at least 1 source citation"

    # 4. Test Session Continuation (Fetch Messages)
    res = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert res.status_code == 200
    messages = res.json()["messages"]
    print(f"4. Session History API: {len(messages)} messages stored in conversation history.")
    assert len(messages) >= 2, "Expected user + assistant messages in history"

    # 5. Test Crawler Status
    res = client.get("/api/crawler/status")
    assert res.status_code == 200
    status_data = res.json()
    print(f"5. Crawler Status API: {status_data['total_pages']} pages, {status_data['total_chunks']} chunks in vector store.")

    print("\n>>> ALL API ENDPOINTS VERIFIED AND WORKING PERFECTLY! <<<")

if __name__ == "__main__":
    test_api()
