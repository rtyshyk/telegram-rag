import time
from typing import Dict, List

import bcrypt
import jwt
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .settings import settings


login_attempts: Dict[str, List[float]] = {}


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_session(username: str) -> str:
    now = int(time.time())
    exp = now + settings.session_ttl_hours * 3600
    payload = {"sub": username, "iat": now, "exp": exp}
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_session(token: str) -> dict:
    return jwt.decode(token, settings.session_secret, algorithms=["HS256"])


def record_attempt(username: str) -> float:
    window = settings.login_rate_window_seconds
    key = username or ""
    attempts = login_attempts.get(key, [])
    now = time.time()
    attempts = [t for t in attempts if now - t < window]
    attempts.append(now)
    login_attempts[key] = attempts
    return attempts[0]


def check_rate_limit(username: str) -> float | None:
    window = settings.login_rate_window_seconds
    key = username or ""
    attempts = login_attempts.get(key, [])
    now = time.time()
    attempts = [t for t in attempts if now - t < window]
    login_attempts[key] = attempts
    if len(attempts) >= settings.login_rate_max_attempts:
        return window - (now - attempts[0])
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.public_paths = {"/healthz", "/auth/login"}

    async def dispatch(self, request: Request, call_next):
        # Always allow CORS preflight to pass through
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in self.public_paths:
            return await call_next(request)

        token = request.cookies.get("rag_session")
        if not token:
            resp = JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
            return resp
        try:
            payload = decode_session(token)
            request.state.user = payload.get("sub")
        except Exception:
            resp = JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
            return resp
        return await call_next(request)
