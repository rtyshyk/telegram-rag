"""Tests for embedding utilities."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from embedder import Embedder
from models import EmbeddingCache, IndexerMetrics
from db import DatabaseManager


class TestEmbedder:
    """Test Embedder class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = AsyncMock(spec=DatabaseManager)
        self.embedder = Embedder(self.mock_db)

    def test_embedder_initialization(self):
        """Test embedder initialization."""
        assert self.embedder.db == self.mock_db
        assert self.embedder.model is not None
        assert self.embedder.batch_size > 0
        assert self.embedder.concurrency > 0
        assert isinstance(self.embedder.metrics, IndexerMetrics)

    def test_compute_text_hash(self):
        """Test text hash computation."""
        text = "Hello world"
        hash1 = self.embedder._compute_text_hash(text)
        hash2 = self.embedder._compute_text_hash(text)

        # Same text should produce same hash
        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA256 hex length

        # Different text should produce different hash
        hash3 = self.embedder._compute_text_hash("Different text")
        assert hash1 != hash3

        # Hash should include language
        hash4 = self.embedder._compute_text_hash(text, lang="en")
        hash5 = self.embedder._compute_text_hash(text, lang="uk")
        assert hash4 != hash5

    def test_vector_serialization(self):
        """Test vector to bytes conversion."""
        vector = [0.1, 0.2, -0.3, 0.4]

        # Convert to bytes and back
        vector_bytes = self.embedder._vector_to_bytes(vector)
        restored_vector = self.embedder._bytes_to_vector(vector_bytes)

        # Should be approximately equal (float precision)
        assert len(restored_vector) == len(vector)
        for i in range(len(vector)):
            assert abs(restored_vector[i] - vector[i]) < 1e-6

    def test_generate_stub_vector(self):
        """Test deterministic stub vector generation."""
        text_hash = "abc123def456"

        # Generate vector
        vector1 = self.embedder._generate_stub_vector(text_hash)
        vector2 = self.embedder._generate_stub_vector(text_hash)

        # Should be deterministic
        assert vector1 == vector2
        assert len(vector1) == 3072  # Default dimension

        # Should be normalized
        magnitude = sum(x * x for x in vector1) ** 0.5
        assert abs(magnitude - 1.0) < 1e-6

        # Different hash should produce different vector
        vector3 = self.embedder._generate_stub_vector("different_hash")
        assert vector1 != vector3

        # Test custom dimension
        vector4 = self.embedder._generate_stub_vector(text_hash, dim=100)
        assert len(vector4) == 100

    @pytest.mark.asyncio
    async def test_embed_empty_texts(self):
        """Test embedding empty text list."""
        results = await self.embedder.embed_texts([])
        assert results == []

    @pytest.mark.asyncio
    async def test_embed_texts_all_cached(self):
        """Test embedding when all texts are cached."""
        texts = ["Hello world", "Test message"]

        # Mock cached embeddings
        cached_vectors = [[0.1, 0.2], [0.3, 0.4]]

        # Pre-compute hashes for provided texts
        hash_map = {t: self.embedder._compute_text_hash(t) for t in texts}

        async def mock_get_cached(text_hash):
            if text_hash == hash_map[texts[0]]:
                return EmbeddingCache(
                    text_hash=text_hash,
                    model=self.embedder.model,
                    dim=2,
                    vector=self.embedder._vector_to_bytes(cached_vectors[0]),
                    chunking_version=1,
                    preprocess_version=1,
                )
            if text_hash == hash_map[texts[1]]:
                return EmbeddingCache(
                    text_hash=text_hash,
                    model=self.embedder.model,
                    dim=2,
                    vector=self.embedder._vector_to_bytes(cached_vectors[1]),
                    chunking_version=1,
                    preprocess_version=1,
                )
            return None

        self.mock_db.get_cached_embedding.side_effect = mock_get_cached

        results = await self.embedder.embed_texts(texts)

        assert len(results) == 2
        assert self.embedder.metrics.embed_cached_hits == 2
        assert self.embedder.metrics.embed_cached_misses == 0

    @pytest.mark.asyncio
    async def test_embed_texts_no_cache(self):
        """Test embedding when no texts are cached."""
        texts = ["Hello world", "Test message"]

        # Mock no cached embeddings
        self.mock_db.get_cached_embedding.return_value = None

        # Mock API response
        # Patch specific attributes rather than replacing whole settings object
        from settings import settings as real_settings

        original = (
            real_settings.openai_stub,
            real_settings.daily_embed_budget_usd,
            real_settings.chunking_version,
            real_settings.preprocess_version,
        )
        real_settings.openai_stub = True
        real_settings.daily_embed_budget_usd = 10.0
        real_settings.chunking_version = 1
        real_settings.preprocess_version = 1

        try:
            results = await self.embedder.embed_texts(texts)
        finally:
            (
                real_settings.openai_stub,
                real_settings.daily_embed_budget_usd,
                real_settings.chunking_version,
                real_settings.preprocess_version,
            ) = original

        assert len(results) == 2
        assert self.embedder.metrics.embed_cached_hits == 0
        assert self.embedder.metrics.embed_cached_misses == 2
        # Should have cached the new embeddings
        assert self.mock_db.cache_embedding.call_count == 2

    @pytest.mark.asyncio
    async def test_embed_texts_dry_run(self):
        """Test embedding in dry run mode."""
        texts = ["Hello world", "Test message"]

        # Mock no cached embeddings
        self.mock_db.get_cached_embedding.return_value = None

        results = await self.embedder.embed_texts(texts, dry_run=True)

        # Should only return cached results (none in this case)
        assert len(results) == 0
        assert self.embedder.metrics.total_tokens > 0  # Cost still estimated
        assert self.embedder.metrics.cost_estimate > 0

    @pytest.mark.asyncio
    async def test_embed_budget_exceeded(self):
        """Test budget protection triggers when estimated cost strictly exceeds budget."""
        # Use unique text each run so no caching interferes
        texts = ["Hello world budget test"]

        self.mock_db.get_cached_embedding.return_value = None

        from settings import settings as real_settings

        original = (real_settings.openai_stub, real_settings.daily_embed_budget_usd)
        # Keep stub mode (no network) so we can calculate cost, then set budget just below estimated cost
        real_settings.openai_stub = True
        # First call (dry_run) with very high budget to compute estimated cost
        real_settings.daily_embed_budget_usd = 999.0
        await self.embedder.embed_texts(texts, dry_run=True)
        estimated_cost = self.embedder.metrics.cost_estimate
        assert estimated_cost > 0
        # Reset metrics and ensure DB cache still misses so cost is recomputed
        self.embedder.metrics.cost_estimate = 0.0
        self.embedder.metrics.total_tokens = 0
        self.mock_db.get_cached_embedding.return_value = None
        # Set budget equal to estimated cost so >= triggers
        real_settings.daily_embed_budget_usd = estimated_cost
        try:
            with pytest.raises(RuntimeError, match="Daily embedding budget exceeded"):
                await self.embedder.embed_texts(texts, dry_run=False)
        finally:
            real_settings.openai_stub, real_settings.daily_embed_budget_usd = original

    @pytest.mark.asyncio
    async def test_embed_batch_stub_mode(self):
        """Test batch embedding in stub mode."""
        batch = [("Hello world", "hash1"), ("Test message", "hash2")]
        semaphore = asyncio.Semaphore(1)

        from settings import settings as real_settings

        original = real_settings.openai_stub
        real_settings.openai_stub = True
        try:
            results = await self.embedder._embed_batch(batch, semaphore)
        finally:
            real_settings.openai_stub = original
        assert len(results) == 2
        for text_hash, vector in results:
            assert isinstance(text_hash, str)
            assert isinstance(vector, list)
            assert len(vector) > 0

    @pytest.mark.asyncio
    async def test_embed_batch_api_retry(self):
        """Test API retry logic."""
        batch = [("Hello world", "hash1")]
        semaphore = asyncio.Semaphore(1)

        # Mock client that fails twice then succeeds
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("API Error")
            return mock_response

        from settings import settings as real_settings

        original = (real_settings.openai_stub, real_settings.backoff_base_ms)
        real_settings.openai_stub = False
        real_settings.backoff_base_ms = 10
        self.embedder.client.embeddings.create = mock_create
        try:
            results = await self.embedder._embed_batch(batch, semaphore)
        finally:
            real_settings.openai_stub, real_settings.backoff_base_ms = original
        assert len(results) == 1
        assert call_count == 3  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    async def test_embed_batch_api_failure(self):
        """Test API failure after all retries."""
        batch = [("Hello world", "hash1")]
        semaphore = asyncio.Semaphore(1)

        # Mock client that always fails
        async def mock_create(*args, **kwargs):
            raise Exception("Persistent API Error")

        from settings import settings as real_settings

        original = (real_settings.openai_stub, real_settings.backoff_base_ms)
        real_settings.openai_stub = False
        real_settings.backoff_base_ms = 1
        self.embedder.client.embeddings.create = mock_create
        try:
            with pytest.raises(Exception, match="Persistent API Error"):
                await self.embedder._embed_batch(batch, semaphore)
        finally:
            real_settings.openai_stub, real_settings.backoff_base_ms = original

    @pytest.mark.asyncio
    async def test_embedding_cache_storage(self):
        """Test that embeddings are properly cached."""
        texts = ["Hello world"]
        self.mock_db.get_cached_embedding.return_value = None

        from settings import settings as real_settings

        original = (
            real_settings.openai_stub,
            real_settings.chunking_version,
            real_settings.preprocess_version,
        )
        try:
            real_settings.openai_stub = True
            real_settings.chunking_version = 1
            real_settings.preprocess_version = 1
            # Compute expected hash after ensuring versions are set
            expected_hash = self.embedder._compute_text_hash(texts[0])
            await self.embedder.embed_texts(texts)
        finally:
            (
                real_settings.openai_stub,
                real_settings.chunking_version,
                real_settings.preprocess_version,
            ) = original
        # Check that cache_embedding was called
        self.mock_db.cache_embedding.assert_called_once()
        # Check the cached embedding structure
        cached_call = self.mock_db.cache_embedding.call_args[0][0]
        assert isinstance(cached_call, EmbeddingCache)
        assert cached_call.text_hash == expected_hash
        assert cached_call.model == self.embedder.model
        assert cached_call.chunking_version == 1
        assert cached_call.preprocess_version == 1

    def test_price_configuration(self):
        """Test that embedding prices are configured."""
        assert "text-embedding-3-small" in self.embedder.price_per_1k_tokens
        assert "text-embedding-3-large" in self.embedder.price_per_1k_tokens
        assert all(price > 0 for price in self.embedder.price_per_1k_tokens.values())

    @pytest.mark.asyncio
    async def test_mixed_cache_scenario(self):
        """Test scenario with some cached and some new embeddings."""
        texts = ["Cached text", "New text"]
        from settings import settings as real_settings

        original = (
            real_settings.openai_stub,
            real_settings.chunking_version,
            real_settings.preprocess_version,
        )
        try:
            real_settings.openai_stub = True
            real_settings.chunking_version = 1
            real_settings.preprocess_version = 1
            # Compute cached hash after ensuring versions match
            cached_hash = self.embedder._compute_text_hash(texts[0])

            async def mock_get_cached(text_hash):
                if text_hash == cached_hash:
                    return EmbeddingCache(
                        text_hash=text_hash,
                        model=self.embedder.model,
                        dim=2,
                        vector=self.embedder._vector_to_bytes([0.1, 0.2]),
                        chunking_version=1,
                        preprocess_version=1,
                    )
                return None

            self.mock_db.get_cached_embedding.side_effect = mock_get_cached

            results = await self.embedder.embed_texts(texts)
        finally:
            (
                real_settings.openai_stub,
                real_settings.chunking_version,
                real_settings.preprocess_version,
            ) = original
        assert len(results) == 2
        # One cache hit (first text), one miss (second text)
        assert self.embedder.metrics.embed_cached_hits == 1
        assert self.embedder.metrics.embed_cached_misses == 1
        # Should cache only the new embedding (second text)
        self.mock_db.cache_embedding.assert_called_once()
