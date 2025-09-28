import contextvars
import logging
import sys
import uuid

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import (
    AuthMiddleware,
    check_rate_limit,
    create_session,
    record_attempt,
    verify_password,
)
from .chat import ChatRequest, get_chat_service
from .models import get_available_models
from .settings import settings
from .search import SearchRequest, get_search_client


CORRELATION_ID_HEADER = "X-Correlation-ID"
_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple
        record.correlation_id = _correlation_id_ctx.get() or "unknown"
        return True


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or uuid.uuid4().hex
        token = _correlation_id_ctx.set(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            _correlation_id_ctx.reset(token)
            raise
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        _correlation_id_ctx.reset(token)
        return response


def _configure_logging() -> None:
    level_name = settings.log_level or "INFO"
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] [corr:%(correlation_id)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )
    correlation_filter = CorrelationIdFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(correlation_filter)
    for handler in root_logger.handlers:
        handler.addFilter(correlation_filter)


_configure_logging()

app = FastAPI()

# Build allowed origins list dynamically (used by CORS middleware added LAST so it's outermost)
_base_allowed = {
    "http://localhost:4321",  # Astro default dev port
    "http://localhost:3000",  # Alt dev port
    "http://127.0.0.1:4321",
    "http://127.0.0.1:3000",
    "http://0.0.0.0:4321",  # Bind-all interface dev
    "http://0.0.0.0:3000",  # Bind-all interface dev
}
if settings.ui_origin:
    _base_allowed.add(settings.ui_origin.rstrip("/"))
allowed_origins = sorted(_base_allowed)
if settings.cors_allow_all:
    allowed_origins = ["*"]

# Auth first (innermost)
app.add_middleware(AuthMiddleware)
# Correlation IDs wrap auth but stay inside CORS
app.add_middleware(CorrelationIdMiddleware)
# CORS last (outermost) so every response (even early auth failures) gets headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
    return get_available_models()


@app.get("/chats")
async def chats():
    """Get list of available chats using Vespa aggregation."""
    try:
        client = await get_search_client()
        chats_list = await client.get_available_chats()
        return {"ok": True, "chats": chats_list}
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to get chats: {e}")
        return {"ok": False, "chats": [], "error": str(e)}


@app.post("/search")
async def search(req: SearchRequest, request: Request):
    client = await get_search_client()
    results = await client.search(req)
    correlation_id = getattr(
        request.state, "correlation_id", _correlation_id_ctx.get() or "unknown"
    )
    return {
        "ok": True,
        "results": [r.model_dump() for r in results],
        "correlation_id": correlation_id,
    }


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """Chat endpoint with RAG capabilities (streaming only)."""
    try:
        user_id = "default_user"
        chat_service = await get_chat_service()

        # Always return streaming response
        return StreamingResponse(
            chat_service.chat_stream(req, user_id),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
            },
        )

    except HTTPException:
        # Re-raise HTTP exceptions (rate limiting, etc.)
        raise
    except Exception as e:
        # Log unexpected errors
        import logging

        logging.getLogger(__name__).error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="internal_error")
