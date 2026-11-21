"""Tests for embedding cost helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cost import (
    DEFAULT_EMBEDDING_USD_PER_1K,
    count_embedding_tokens,
    embedding_price_per_1k,
    estimate_embedding_cost,
)


def test_qwen_embedding_price():
    assert embedding_price_per_1k("Qwen/Qwen3-Embedding-8B") == 0.00001


def test_unknown_model_uses_nebius_default():
    assert (
        embedding_price_per_1k("vendor/unknown-embed") == DEFAULT_EMBEDDING_USD_PER_1K
    )


def test_count_embedding_tokens_nonzero():
    tokens = count_embedding_tokens(["hello world", "second line"])
    assert tokens > 0


def test_estimate_embedding_cost_qwen():
    texts = ["x"] * 1000
    result = estimate_embedding_cost(texts, "Qwen/Qwen3-Embedding-8B")
    assert result["tokens"] > 0
    expected = (result["tokens"] / 1000.0) * 0.00001
    assert abs(float(result["cost_usd"]) - expected) < 1e-12
