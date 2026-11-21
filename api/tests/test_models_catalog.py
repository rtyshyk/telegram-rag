"""Tests for provider chat model catalog."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from app.models import (
    entry_to_model_option,
    fetch_chat_models_from_provider,
    is_chat_model_entry,
    model_option_sort_key,
    natural_sort_key,
    normalize_modality,
)
from app.settings import settings


NEBIUS_DEEPSEEK_REFERENCE = [
    ("deepseek-ai/DeepSeek-R1-0528", "DeepSeek-R1-0528"),
    ("deepseek-ai/DeepSeek-V3-0324", "DeepSeek-V3-0324"),
    ("deepseek-ai/DeepSeek-V4-Flash-0731", "DeepSeek-V4-Flash-0731"),
    ("deepseek-ai/DeepSeek-V4-Pro", "DeepSeek-V4-Pro"),
    ("deepseek-ai/DeepSeek-V4-Pro-0813", "DeepSeek-V4-Pro-0813"),
]


def test_normalize_modality_maps_text_to_text():
    assert normalize_modality("text-to-text") == "text->text"
    assert normalize_modality("text+image-to-text") == "text+image->text"


@pytest.mark.parametrize("model_id,label", NEBIUS_DEEPSEEK_REFERENCE)
def test_deepseek_reference_text_to_text_passes_filter(model_id: str, label: str):
    assert is_chat_model_entry(
        {
            "id": model_id,
            "name": label,
            "architecture": {"modality": "text-to-text"},
        }
    )


def test_is_chat_model_entry_keeps_missing_modality():
    assert is_chat_model_entry({"id": "gpt-4o"}) is True


def test_is_chat_model_entry_filters_non_text():
    assert (
        is_chat_model_entry(
            {
                "id": "BAAI/bge-en-icl",
                "architecture": {"modality": "text->embedding"},
            }
        )
        is False
    )
    assert (
        is_chat_model_entry(
            {
                "id": "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "architecture": {"modality": "text->text"},
            }
        )
        is True
    )
    assert (
        is_chat_model_entry(
            {
                "id": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
                "architecture": {"modality": "text+image->text"},
            }
        )
        is True
    )
    assert (
        is_chat_model_entry(
            {
                "id": "example/vl",
                "architecture": {"modality": "image+text->text+image"},
            }
        )
        is True
    )
    assert (
        is_chat_model_entry(
            {
                "id": "example/text-to-image",
                "architecture": {"modality": "text->image"},
            }
        )
        is False
    )


def test_natural_sort_key_orders_numeric_segments():
    assert natural_sort_key("Llama 7B") < natural_sort_key("Llama 72B")
    assert natural_sort_key("Model 3.1") < natural_sort_key("Model 3.10")


def test_model_option_sort_key_tiebreaks_by_id():
    a = {"id": "vendor/a", "label": "Same"}
    b = {"id": "vendor/b", "label": "Same"}
    assert model_option_sort_key(a) < model_option_sort_key(b)


def test_entry_to_model_option_uses_name():
    option = entry_to_model_option(
        {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct", "name": "Llama 70B"}
    )
    assert option == {
        "id": "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "label": "Llama 70B",
    }


@pytest.mark.asyncio
async def test_fetch_chat_models_from_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        settings,
        "openai_base_url",
        "https://api.tokenfactory.nebius.com/v1/",
    )

    payload = {
        "data": [
            {
                "id": "BAAI/bge-en-icl",
                "architecture": {"modality": "text->embedding"},
            },
            {
                "id": "meta-llama/Meta-Llama-3.1-72B-Instruct",
                "name": "Llama 72B",
                "architecture": {"modality": "text->text"},
            },
            {
                "id": "meta-llama/Meta-Llama-3.1-7B-Instruct",
                "name": "Llama 7B",
                "architecture": {"modality": "text->text"},
            },
            {
                "id": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
                "name": "DeepSeek Flash",
                "architecture": {"modality": "text+image->text"},
            },
            {"id": "gpt-4o"},
        ]
    }

    mock_response = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.models.httpx.AsyncClient", return_value=mock_client):
        models = await fetch_chat_models_from_provider()

    assert len(models) == 4
    labels = [m["label"] for m in models]
    assert labels == [
        "DeepSeek Flash",
        "gpt-4o",
        "Llama 7B",
        "Llama 72B",
    ]
    ids = {m["id"] for m in models}
    assert "meta-llama/Meta-Llama-3.1-7B-Instruct" in ids
    assert "meta-llama/Meta-Llama-3.1-72B-Instruct" in ids
    assert "gpt-4o" in ids
    assert "BAAI/bge-en-icl" not in ids


def test_models_endpoint_provider_error(monkeypatch):
    from test_auth import get_client, login, reset_attempts

    async def _fail():
        raise httpx.HTTPStatusError(
            "bad",
            request=httpx.Request("GET", "http://test"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr("app.main.fetch_chat_models_from_provider", _fail)
    reset_attempts()
    client = get_client()
    assert login(client).status_code == 200
    response = client.get("/models")
    assert response.status_code == 502
