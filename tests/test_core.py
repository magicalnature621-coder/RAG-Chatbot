"""
Offline tests: no network, no LLM calls, no crawling. Run with `pytest tests`.
"""
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.main import app
from backend.rag.llm import LLMProvider
from backend.rag.vector_store import VectorStore

client = TestClient(app)


def _register(prefix="user"):
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert res.status_code == 200, res.text
    body = res.json()
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture(autouse=True)
def local_llm():
    # Never call a real model from tests, even if .env holds an API key.
    database.set_setting("llm_provider", "local")
    yield


def test_forged_token_is_rejected():
    user, _ = _register()
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer tok_{user['id']}_forged"})
    assert res.status_code == 401


def test_login_token_works_and_logout_revokes_it():
    user, headers = _register()
    assert client.get("/api/auth/me", headers=headers).json()["user"]["id"] == user["id"]
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_short_password_rejected():
    res = client.post("/api/auth/register", json={"username": f"u_{uuid.uuid4().hex[:6]}", "password": "abc"})
    assert res.status_code == 400


def test_config_and_sync_require_auth():
    assert client.post("/api/config", json={"llm_provider": "groq"}).status_code == 401
    assert client.post("/api/crawler/sync").status_code == 401


def test_config_rejects_unknown_provider():
    _, headers = _register()
    res = client.post("/api/config", json={"llm_provider": "skynet"}, headers=headers)
    assert res.status_code == 400


def test_cannot_delete_other_users_session_messages():
    _, owner = _register("owner")
    _, other = _register("other")
    sid = client.post("/api/sessions", json={}, headers=owner).json()["session"]["id"]
    client.post(f"/api/sessions/{sid}/message", json={"content": "hello"}, headers=owner)

    assert client.delete(f"/api/sessions/{sid}", headers=other).status_code == 404
    assert len(client.get(f"/api/sessions/{sid}", headers=owner).json()["messages"]) == 2


def test_chat_flow_in_local_mode():
    _, headers = _register()
    sid = client.post("/api/sessions", json={}, headers=headers).json()["session"]["id"]
    res = client.post(
        f"/api/sessions/{sid}/message",
        json={"content": "What B.Tech branches are offered?"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "local"
    assert body["message"]["content"]
    history = client.get(f"/api/sessions/{sid}", headers=headers).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["session"]["title"] != "New Conversation"


def test_explicit_provider_choice_is_honored(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    llm = LLMProvider()

    database.set_setting("llm_provider", "gemini")
    assert llm._candidate_providers() == ["gemini", "groq"]

    database.set_setting("llm_provider", "local")
    assert llm._candidate_providers() == []
    assert llm.get_active_provider() == "local"


def test_failed_provider_falls_back_and_reports_local(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    database.set_setting("llm_provider", "groq")
    llm = LLMProvider()
    monkeypatch.setattr(llm, "_call_groq", lambda key, messages: "")  # e.g. empty reasoning-model output
    chunk = {"title": "T", "source_url": "https://x", "text": "The hostel fee is 5000 per semester."}
    answer, provider = llm.generate("hostel fee", [chunk])
    assert provider == "local"
    assert "hostel" in answer.lower()


def test_vector_store_concurrent_upsert_and_search(tmp_path):
    store = VectorStore(index_path=str(tmp_path / "idx.json"))
    text = " ".join(f"word{i} placement hostel fees" for i in range(300))
    errors = []

    def writer():
        try:
            for i in range(15):
                store.upsert_document(f"doc{i % 3}", f"Doc {i}", text, f"https://x/{i % 3}")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    def reader():
        try:
            for _ in range(60):
                for r in store.search("placement fees", top_k=3):
                    assert r["doc_id"] in {"doc0", "doc1", "doc2"}
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert store.get_stats()["total_documents"] == 3
