"""Pytest configuration and fixtures for indexer tests."""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock()
    settings.target_chunk_tokens = 512
    settings.chunk_overlap_tokens = 50
    settings.embed_model = "text-embedding-3-small"
    settings.embed_batch_size = 10
    settings.embed_concurrency = 3
    settings.daily_embed_budget_usd = 10.0
    settings.chunking_version = 1
    settings.preprocess_version = 1
    settings.openai_stub = True
    settings.backoff_base_ms = 100
    settings.vespa_endpoint = "http://localhost:8080"
    settings.openai_api_key = "test-api-key"
    return settings


@pytest.fixture
def mock_db():
    """Mock database manager for testing."""
    db = AsyncMock()
    db.get_cached_embedding.return_value = None
    db.cache_embedding.return_value = None
    return db


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    client = AsyncMock()

    # Mock embeddings response
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1, 0.2, 0.3] * 1024  # 3072 dimensions

    mock_response = MagicMock()
    mock_response.data = [mock_embedding_data]

    client.embeddings.create.return_value = mock_response
    return client


@pytest.fixture
def mock_vespa_client():
    """Mock Vespa HTTP client for testing."""
    client = AsyncMock()

    # Mock successful responses by default
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    client.post.return_value = mock_response
    client.delete.return_value = mock_response
    client.get.return_value = mock_response
    client.aclose.return_value = None

    return client


@pytest.fixture
def sample_vespa_document():
    """Sample VespaDocument for testing."""
    from indexer.models import VespaDocument

    return VespaDocument(
        id="test:123:0:v1",
        chat_id="test_chat",
        message_id=123,
        chunk_idx=0,
        source_title="Test Chat",
        sender="Test User",
        sender_username="testuser",
        chat_type="private",
        message_date=1692825600,
        edit_date=None,
        thread_id=None,
        has_link=False,
        text="This is a test message for unit testing purposes.",
        bm25_text="This is a test message for unit testing purposes.",
        vector={"values": [0.1, 0.2, 0.3]},
    )


@pytest.fixture
def sample_embedding_cache():
    """Sample EmbeddingCache for testing."""
    from indexer.models import EmbeddingCache
    import struct

    vector = [0.1, 0.2, 0.3]
    vector_bytes = struct.pack(f"{len(vector)}f", *vector)

    return EmbeddingCache(
        text_hash="abc123def456",
        model="text-embedding-3-small",
        dim=3,
        vector=vector_bytes,
        lang="en",
        chunking_version=1,
        preprocess_version=1,
    )


@pytest.fixture
def sample_chunk():
    """Sample Chunk for testing."""
    from indexer.models import Chunk

    return Chunk(
        chunk_id="test:123:0",
        chat_id="test_chat",
        message_id=123,
        chunk_idx=0,
        text_hash="abc123def456",
        message_date=1692825600,
        edit_date=None,
        sender="Test User",
        sender_username="testuser",
        chat_type="private",
        thread_id=None,
        has_link=False,
    )


@pytest.fixture
def temp_directory():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture(autouse=True)
def clean_environment():
    """Clean environment variables before each test."""
    # Store original values
    original_env = {}
    env_vars_to_clean = [
        "OPENAI_API_KEY",
        "OPENAI_STUB",
        "VESPA_ENDPOINT",
        "DATABASE_URL",
    ]

    for var in env_vars_to_clean:
        if var in os.environ:
            original_env[var] = os.environ[var]
            del os.environ[var]

    yield

    # Restore original values
    for var, value in original_env.items():
        os.environ[var] = value


@pytest.fixture
def mock_telethon_message():
    """Mock Telethon message object."""
    message = MagicMock()
    message.id = 123
    message.date = MagicMock()
    message.date.timestamp.return_value = 1692825600
    message.edit_date = None
    message.text = "This is a test message"
    message.raw_text = "This is a test message"
    message.reply_to = None
    message.forward = None

    # Mock sender
    sender = MagicMock()
    sender.first_name = "Test"
    sender.last_name = "User"
    sender.username = "testuser"
    message.sender = sender

    return message


@pytest.fixture
def mock_telethon_chat():
    """Mock Telethon chat object."""
    chat = MagicMock()
    chat.id = 123456
    chat.title = "Test Chat"
    chat.megagroup = False
    chat.channel = False
    chat.user_id = None
    return chat


class AsyncIterator:
    """Helper class for async iteration in tests."""

    def __init__(self, items):
        self.items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def async_iterator():
    """Factory for creating async iterators in tests."""
    return AsyncIterator
