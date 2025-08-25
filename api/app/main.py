from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import (
    AuthMiddleware,
    check_rate_limit,
    create_session,
    record_attempt,
    verify_password,
)
from .settings import settings
from .search import SearchRequest, get_search_client

app = FastAPI()

# Build allowed origins list dynamically (used by CORS middleware added LAST so it's outermost)
_base_allowed = {
    "http://localhost:4321",  # Astro default dev port
    "http://localhost:3000",  # Alt dev port
    "http://127.0.0.1:4321",
    "http://127.0.0.1:3000",
}
if settings.ui_origin:
    _base_allowed.add(settings.ui_origin.rstrip("/"))
allowed_origins = sorted(_base_allowed)
if settings.cors_allow_all:
    allowed_origins = ["*"]

# CORS FIRST (outermost) so every response (even early auth failures) gets headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Auth after CORS
app.add_middleware(AuthMiddleware)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.post("/auth/login")
async def login(request: Request, response: Response):
    data = await request.json()
    username = data.get("username") or ""
    password = data.get("password") or ""
    retry = check_rate_limit(username)
    if retry:
        return JSONResponse(
            {"ok": False, "error": "too_many_attempts"},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(int(retry))},
        )
    if username != settings.app_user or not verify_password(
        password, settings.app_user_hash_bcrypt
    ):
        record_attempt(username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )
    token = create_session(username)
    response = JSONResponse({"ok": True})
    # Only mark secure if the request scheme is https (avoids losing cookie on http://localhost dev)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        "rag_session",
        token,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


@app.post("/auth/logout")
async def logout(response: Response):
    response = JSONResponse({"ok": True})
    response.delete_cookie("rag_session", path="/")
    return response


@app.get("/models")
async def models() -> list[dict[str, str]]:
    return [
        {"label": "gpt 5", "id": "gpt-5"},
        {"label": "gpt5 mini", "id": "gpt-5-mini"},
        {"label": "gpt5 nano", "id": "gpt-5-nano"},
    ]


@app.post("/search")
async def search(req: SearchRequest):
    client = await get_search_client()
    results = await client.search(req)
    return {"ok": True, "results": [r.model_dump() for r in results]}
