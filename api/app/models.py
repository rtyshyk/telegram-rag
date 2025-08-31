"""Model configuration and utilities."""

from typing import Dict, List


# Single source of truth for model configurations
AVAILABLE_MODELS: List[Dict[str, str]] = [
    {"label": "gpt 5", "id": "gpt-5"},
    {"label": "gpt5 mini", "id": "gpt-5-mini"},
    {"label": "gpt5 nano", "id": "gpt-5-nano"},
]

# Create mapping from label to id for easy lookup
MODEL_LABEL_TO_ID: Dict[str, str] = {
    model["label"]: model["id"] for model in AVAILABLE_MODELS
}

# Default model ID (first in the list)
DEFAULT_MODEL_ID = AVAILABLE_MODELS[0]["id"]


def get_available_models() -> List[Dict[str, str]]:
    """Get list of available models for API responses."""
    return AVAILABLE_MODELS.copy()


def resolve_model_id(model_label: str | None) -> str:
    """Resolve model label to actual model ID."""
    if not model_label:
        return DEFAULT_MODEL_ID
    return MODEL_LABEL_TO_ID.get(model_label, DEFAULT_MODEL_ID)
