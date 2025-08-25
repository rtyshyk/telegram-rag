import os
import sys
import pathlib
from fastapi.testclient import TestClient

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

# Set required env variables
os.environ.setdefault("APP_USER", "admin")
import bcrypt

hash_pw = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
os.environ.setdefault("APP_USER_HASH_BCRYPT", hash_pw)
os.environ.setdefault("SESSION_SECRET", "testsecret" * 2)

from app.main import app  # noqa: E402
from app import search as search_module  # noqa: E402


def get_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient):
    return client.post(
        "/auth/login", json={"username": "admin", "password": "password"}
    )


def test_search_requires_auth():
    client = get_client()
    r = client.post("/search", json={"q": "hello"})
    assert r.status_code == 401


def test_search_builds_yql_and_caches_embedding():
    client = get_client()
    assert login(client).status_code == 200

    calls: list[str] = []

    async def fake_embed(q: str, model: str):
        calls.append(q)
        return [0.1, 0.2, 0.3]

    orig = search_module.embed_query
    search_module.embed_query = fake_embed

    try:
        # first call
        r = client.post(
            "/search",
            json={"q": "ssh key", "debug": True, "model_label": "gpt 5"},
        )
        assert r.status_code == 200
        data = r.json()
        yql = data["debug"]["vespa_query"]
        assert "nearestNeighbor" in yql
        assert "ssh" in yql and "key" in yql
        assert len(calls) == 1

        # second call with same query but different sort -> should use cache
        r = client.post(
            "/search",
            json={"q": "ssh key", "sort": "recency", "debug": False},
        )
        assert r.status_code == 200
        assert len(calls) == 1
    finally:
        search_module.embed_query = orig


def test_recency_with_filters_allows_empty_query():
    client = get_client()
    assert login(client).status_code == 200
    r = client.post(
        "/search",
        json={"q": "", "sort": "recency", "filters": {"chat_ids": ["1"]}},
    )
    assert r.status_code == 200


def test_missing_query_and_filters_errors():
    client = get_client()
    assert login(client).status_code == 200
    r = client.post("/search", json={"q": "", "sort": "recency"})
    assert r.status_code == 400
    assert r.json()["detail"] == "q_or_filter_required"


def test_has_link_filter_included():
    client = get_client()
    assert login(client).status_code == 200
    r = client.post(
        "/search",
        json={
            "q": "link stuff",
            "filters": {"has_link": True},
            "debug": True,
        },
    )
    assert r.status_code == 200
    assert "has_link contains true" in r.json()["debug"]["vespa_query"]
