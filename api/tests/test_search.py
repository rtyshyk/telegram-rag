import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from api.app.auth import create_session
from api.app.search import get_search_client, SearchRequest


def auth_cookie() -> dict[str, str]:
    token = create_session("tester")
    return {"rag_session": token}


def test_search_unauthorized():
    client = TestClient(app)
    resp = client.post("/search", json={"q": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_stub(monkeypatch):
    client = TestClient(app)
    search_client = await get_search_client()

    async def fake_search(req: SearchRequest):  # type: ignore
        return []

    search_client.search = fake_search  # type: ignore
    resp = client.post("/search", cookies=auth_cookie(), json={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["results"] == []
