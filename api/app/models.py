"""Chat model catalog from the configured OpenAI-compatible provider."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

import httpx

from .settings import settings

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_V1 = "https://api.openai.com/v1"

# Input and output must include a text segment (e.g. text->text, text+image->text).
CHAT_MODALITY_PATTERN = re.compile(
    r"^(?:[^+]+\+)*text(?:\+[^+]+)*->(?:[^+]+\+)*text(?:\+[^+]+)*$"
)

MODELS_PAGE_LIMIT = 100


def normalize_modality(modality: str) -> str:
    """Map provider/UI forms like text-to-text onto text->text."""
    return modality.strip().replace("-to-", "->")


def _provider_models_url() -> str:
    base = (settings.openai_base_url or DEFAULT_OPENAI_V1).rstrip("/")
    return f"{base}/models?verbose=true"


def is_chat_model_entry(entry: Dict[str, Any]) -> bool:
    """Include chat models whose modality has text input and text output."""
    architecture = entry.get("architecture")
    if not isinstance(architecture, dict):
        return True
    modality = architecture.get("modality")
    if modality is None:
        return True
    if not isinstance(modality, str):
        return False
    return CHAT_MODALITY_PATTERN.fullmatch(normalize_modality(modality)) is not None


async def _fetch_models_payload(client: httpx.AsyncClient, url: str) -> List[Dict[str, Any]]:
    """Load all model pages when the provider uses cursor pagination."""
    entries: List[Dict[str, Any]] = []
    after: str | None = None

    while True:
        page_url = url
        if after:
            separator = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{separator}after={after}"

        response = await client.get(
            page_url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Invalid models list response from provider")

        entries.extend(entry for entry in data if isinstance(entry, dict))
        if not payload.get("has_more"):
            break
        if not data:
            break
        next_after = payload.get("last_id") or data[-1].get("id")
        if not isinstance(next_after, str) or next_after == after:
            break
        after = next_after

    return entries


def natural_sort_key(text: str) -> Tuple[Any, ...]:
    """Sort key that orders embedded numbers numerically (7 before 72)."""

    def token(part: str) -> Any:
        return int(part) if part.isdigit() else part.lower()

    return tuple(token(part) for part in re.split(r"(\d+)", text) if part)


def model_option_sort_key(item: Dict[str, str]) -> Tuple[Any, ...]:
    label_key = natural_sort_key(item["label"])
    return label_key + (item["id"].lower(),)


def entry_to_model_option(entry: Dict[str, Any]) -> Dict[str, str]:
    model_id = entry.get("id")
    if not model_id or not isinstance(model_id, str):
        raise ValueError("Model entry missing id")
    name = entry.get("name")
    label = name if isinstance(name, str) and name.strip() else model_id
    return {"id": model_id, "label": label}


async def fetch_chat_models_from_provider() -> List[Dict[str, str]]:
    """List chat models from GET /v1/models?verbose=true."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")

    base_url = _provider_models_url()
    url = (
        f"{base_url}&limit={MODELS_PAGE_LIMIT}"
        if "?" in base_url
        else f"{base_url}?limit={MODELS_PAGE_LIMIT}"
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        data = await _fetch_models_payload(client, url)

    models: List[Dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not is_chat_model_entry(entry):
            continue
        try:
            models.append(entry_to_model_option(entry))
        except ValueError:
            logger.warning("Skipping invalid model entry: %s", entry)
            continue

    models.sort(key=model_option_sort_key)
    if not models:
        raise ValueError("No chat models returned from provider")
    return models
