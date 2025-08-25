import os, pathlib, sys
from fastapi.testclient import TestClient

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

os.environ.setdefault("APP_USER", "admin")
os.environ.setdefault("APP_USER_HASH_BCRYPT", "bcrypt$2b$12$placeholderhashhashhashhashhashh")
os.environ.setdefault("SESSION_SECRET", "secret" * 4)

from app.main import app  # noqa: E402

client = TestClient(app, base_url="http://localhost")

ALLOWED_ORIGIN = "http://localhost:4321"
ALT_ORIGIN = "http://0.0.0.0:4321"


def test_preflight_includes_cors_headers():
    r = client.options(
        "/search",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "access-control-allow-methods" in {k.lower() for k in r.headers.keys()}


def test_unauthorized_request_has_cors_headers():
    r = client.post("/search", json={"q": "hello"}, headers={"Origin": ALLOWED_ORIGIN})
    # Expect 401 due to missing cookie but still CORS headers
    assert r.status_code == 401 or r.status_code == 200  # search route requires auth
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_preflight_alt_origin():
    r = client.options(
        "/search",
        headers={
            "Origin": ALT_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == ALT_ORIGIN
