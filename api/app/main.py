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

app = FastAPI()
app.add_middleware(AuthMiddleware)

if settings.ui_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.ui_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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
    response.set_cookie(
        "rag_session",
        token,
        httponly=True,
        samesite="lax",
        secure=True,
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
