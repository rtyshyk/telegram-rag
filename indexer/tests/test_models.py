"""Tests for data models."""

import pytest
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import TgSyncState, EmbeddingCache, Chunk, VespaDocument, IndexerMetrics


class TestTgSyncState:
    """Test TgSyncState model."""

    def test_create_empty_state(self):
        """Test creating empty sync state."""
        state = TgSyncState(chat_id="123")
        assert state.chat_id == "123"
        assert state.last_message_id is None
        assert state.last_edit_ts is None

    def test_create_full_state(self):
        """Test creating full sync state."""
        state = TgSyncState(chat_id="123", last_message_id=456, last_edit_ts=1692825600)
        assert state.chat_id == "123"
        assert state.last_message_id == 456
        assert state.last_edit_ts == 1692825600

    def test_state_serialization(self):
        """Test state can be serialized/deserialized."""
        state = TgSyncState(chat_id="123", last_message_id=456, last_edit_ts=1692825600)

        # Test dict conversion
        state_dict = state.model_dump()
        restored = TgSyncState(**state_dict)

        assert restored.chat_id == state.chat_id
        assert restored.last_message_id == state.last_message_id
        assert restored.last_edit_ts == state.last_edit_ts


class TestEmbeddingCache:
    """Test EmbeddingCache model."""

    def test_create_cache_entry(self):
        """Test creating cache entry."""
        vector_bytes = b"\x00\x01\x02\x03"
        cache = EmbeddingCache(
            text_hash="abc123",
            model="text-embedding-3-small",
            dim=1536,
            vector=vector_bytes,
            chunking_version=1,
            preprocess_version=1,
        )

        assert cache.text_hash == "abc123"
        assert cache.model == "text-embedding-3-small"
        assert cache.dim == 1536
        assert cache.vector == vector_bytes
        assert cache.lang is None
        assert cache.chunking_version == 1
        assert cache.preprocess_version == 1

    def test_cache_with_language(self):
        """Test cache entry with language."""
        cache = EmbeddingCache(
            text_hash="abc123",
            model="text-embedding-3-small",
            dim=1536,
            vector=b"\x00\x01",
            lang="en",
            chunking_version=1,
            preprocess_version=1,
        )

        assert cache.lang == "en"


class TestChunk:
    """Test Chunk model."""

    def test_create_basic_chunk(self):
        """Test creating basic chunk."""
        chunk = Chunk(
            chunk_id="chat123:msg456:0",
            chat_id="123",
            message_id=456,
            chunk_idx=0,
            text_hash="abc123",
            message_date=1692825600,
        )

        assert chunk.chunk_id == "chat123:msg456:0"
        assert chunk.chat_id == "123"
        assert chunk.message_id == 456
        assert chunk.chunk_idx == 0
        assert chunk.text_hash == "abc123"
        assert chunk.message_date == 1692825600
        assert chunk.edit_date is None
        assert chunk.deleted_at is None
        assert chunk.sender is None
        assert chunk.has_link is False

    def test_create_full_chunk(self):
        """Test creating chunk with all fields."""
        chunk = Chunk(
            chunk_id="chat123:msg456:0",
            chat_id="123",
            message_id=456,
            chunk_idx=0,
            text_hash="abc123",
            message_date=1692825600,
            edit_date=1692825700,
            sender="TestUser",
            sender_username="@testuser",
            chat_type="private",
            thread_id=789,
            has_link=True,
        )

        assert chunk.edit_date == 1692825700
        assert chunk.sender == "TestUser"
        assert chunk.sender_username == "@testuser"
        assert chunk.chat_type == "private"
        assert chunk.thread_id == 789
        assert chunk.has_link is True


class TestVespaDocument:
    """Test VespaDocument model."""

    def test_create_basic_document(self):
        """Test creating basic Vespa document."""
        doc = VespaDocument(
            id="doc123",
            chat_id="123",
            message_id=456,
            chunk_idx=0,
            message_date=1692825600,
            text="Hello world",
            bm25_text="Hello world",
            vector_small={"values": [0.1, 0.2, 0.3]},
        )

        assert doc.id == "doc123"
        assert doc.chat_id == "123"
        assert doc.message_id == 456
        assert doc.chunk_idx == 0
        assert doc.message_date == 1692825600
        assert doc.text == "Hello world"
        assert doc.bm25_text == "Hello world"
        assert doc.vector_small == {"values": [0.1, 0.2, 0.3]}
        assert doc.has_link is False

    def test_create_full_document(self):
        """Test creating full Vespa document."""
        doc = VespaDocument(
            id="doc123",
            chat_id="123",
            message_id=456,
            chunk_idx=0,
            source_title="Test Chat",
            sender="TestUser",
            sender_username="@testuser",
            chat_type="group",
            message_date=1692825600,
            edit_date=1692825700,
            thread_id=789,
            has_link=True,
            text="Hello world with link https://example.com",
            bm25_text="Hello world with link https://example.com",
            vector_small={"values": [0.1, 0.2, 0.3]},
        )

        assert doc.source_title == "Test Chat"
        assert doc.sender == "TestUser"
        assert doc.sender_username == "@testuser"
        assert doc.chat_type == "group"
        assert doc.edit_date == 1692825700
        assert doc.thread_id == 789
        assert doc.has_link is True


class TestIndexerMetrics:
    """Test IndexerMetrics model."""

    def test_create_empty_metrics(self):
        """Test creating empty metrics."""
        metrics = IndexerMetrics()

        assert metrics.messages_scanned == 0
        assert metrics.messages_indexed == 0
        assert metrics.chunks_written == 0
        assert metrics.embed_calls == 0
        assert metrics.embed_cached_hits == 0
        assert metrics.embed_cached_misses == 0
        assert metrics.vespa_feed_success == 0
        assert metrics.vespa_feed_retries == 0
        assert metrics.vespa_feed_failures == 0
        assert metrics.total_tokens == 0
        assert metrics.cost_estimate == 0.0

    def test_metrics_accumulation(self):
        """Test metrics can be updated."""
        metrics = IndexerMetrics()

        # Simulate processing
        metrics.messages_scanned = 10
        metrics.messages_indexed = 8
        metrics.chunks_written = 12
        metrics.embed_calls = 8
        metrics.vespa_feed_success = 12
        metrics.total_tokens = 1500
        metrics.cost_estimate = 0.0003

        assert metrics.messages_scanned == 10
        assert metrics.messages_indexed == 8
        assert metrics.chunks_written == 12
        assert metrics.embed_calls == 8
        assert metrics.vespa_feed_success == 12
        assert metrics.total_tokens == 1500
        assert metrics.cost_estimate == 0.0003

    def test_metrics_serialization(self):
        """Test metrics can be serialized."""
        metrics = IndexerMetrics(
            messages_scanned=10,
            messages_indexed=8,
            total_tokens=1500,
            cost_estimate=0.0003,
        )

        # Test dict conversion
        metrics_dict = metrics.model_dump()
        restored = IndexerMetrics(**metrics_dict)

        assert restored.messages_scanned == metrics.messages_scanned
        assert restored.messages_indexed == metrics.messages_indexed
        assert restored.total_tokens == metrics.total_tokens
        assert restored.cost_estimate == metrics.cost_estimate
