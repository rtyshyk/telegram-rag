import os
import sys
import pathlib
import bcrypt
from fastapi.testclient import TestClient

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

os.environ.setdefault("APP_USER", "admin")
hash_pw = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
os.environ.setdefault("APP_USER_HASH_BCRYPT", hash_pw)
os.environ.setdefault("SESSION_SECRET", "testsecret" * 2)

from app.main import app  # noqa: E402
import app.auth as auth
from app.search import get_search_client


def reset_attempts():
    auth.login_attempts.clear()


def get_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient):
    return client.post(
        "/auth/login", json={"username": "admin", "password": "password"}
    )


def test_login_success_sets_cookie():
    reset_attempts()
    client = get_client()
    r = login(client)
    assert r.status_code == 200
    assert r.cookies.get("rag_session")


def test_login_wrong_password():
    reset_attempts()
    client = get_client()
    r = client.post("/auth/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 401


def test_login_rate_limit_then_429():
    reset_attempts()
    client = get_client()
    for _ in range(5):
        client.post("/auth/login", json={"username": "admin", "password": "bad"})
    r = client.post("/auth/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 429


def test_rate_limit_is_per_username():
    reset_attempts()
    client = get_client()
    for _ in range(5):
        client.post("/auth/login", json={"username": "admin", "password": "bad"})
    r = client.post("/auth/login", json={"username": "other", "password": "bad"})
    assert r.status_code == 401


def test_models_requires_auth():
    reset_attempts()
    client = get_client()
    r = client.get("/models")
    assert r.status_code == 401


def test_models_returns_mapping():
    reset_attempts()
    client = get_client()
    assert login(client).status_code == 200
    r = client.get("/models")
    assert r.status_code == 200
    data = r.json()
    assert any(m["id"] == "gpt-5" for m in data)


def test_logout_clears_cookie():
    reset_attempts()
    client = get_client()
    assert login(client).status_code == 200
    r = client.post("/auth/logout")
    assert r.status_code == 200
    r = client.get("/models")
    assert r.status_code == 401


def test_search_response_includes_correlation_id():
    reset_attempts()
    client = get_client()
    assert login(client).status_code == 200

    class _FakeSearchClient:
        async def search(self, req):  # pragma: no cover - simple stub
            return []

    async def _override_search_client():
        return _FakeSearchClient()

    app.dependency_overrides[get_search_client] = _override_search_client
    try:
        response = client.post("/search", json={"q": "hello"})
    finally:
        app.dependency_overrides.pop(get_search_client, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["results"] == []
    correlation_id = payload.get("correlation_id")
    assert correlation_id
    assert response.headers.get("X-Correlation-ID") == correlation_id
