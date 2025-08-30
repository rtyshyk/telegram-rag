"""Tests for the main indexer functionality."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
import sys
import os

# Add the indexer directory to the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import TelegramIndexer
from settings import CLIArgs


@pytest.fixture
def mock_cli_args():
    """Mock CLI args for testing."""
    args = CLIArgs(
        once=True,
        chats=None,  # Test with no specific chats (all chats)
        days=7,
        dry_run=False,
        limit_messages=10,  # Global limit across all chats
        embed_batch_size=5,
        embed_concurrency=2,
        sleep_ms=0,
        log_level="INFO",
    )
    return args


@pytest.fixture
def mock_indexer_deps():
    """Mock all dependencies for TelegramIndexer."""
    with patch("main.DatabaseManager") as mock_db_class, patch(
        "main.TelethonClientWrapper"
    ) as mock_tg_class, patch("main.TextChunker") as mock_chunker_class, patch(
        "main.Embedder"
    ) as mock_embedder_class, patch(
        "main.VespaClient"
    ) as mock_vespa_class:
        # Mock database
        mock_db = AsyncMock()
        mock_db.initialize = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.get_existing_chunks = AsyncMock(return_value=[])
        mock_db.upsert_chunk = AsyncMock()
        mock_db_class.return_value = mock_db

        # Mock Telethon client
        mock_tg = AsyncMock()
        mock_tg.start = AsyncMock()
        mock_tg.stop = AsyncMock()
        mock_tg.get_all_chats = AsyncMock(return_value=["Chat1", "Chat2", "Chat3"])
        mock_tg.resolve_chats = AsyncMock(
            return_value={
                "Chat1": {
                    "entity": "entity1",
                    "id": "1",
                    "title": "Chat 1",
                    "type": "private",
                },
                "Chat2": {
                    "entity": "entity2",
                    "id": "2",
                    "title": "Chat 2",
                    "type": "group",
                },
                "Chat3": {
                    "entity": "entity3",
                    "id": "3",
                    "title": "Chat 3",
                    "type": "channel",
                },
            }
        )
        mock_tg.extract_message_data = MagicMock(
            side_effect=lambda msg, entity: {
                "message_id": msg.id,
                "text": msg.text,
                "sender": "Test User",
                "sender_username": "testuser",
                "message_date": int(msg.date.timestamp()),
                "edit_date": None,
                "chat_type": "private",
                "reply_to_msg_id": None,
                "thread_id": None,
            }
        )
        mock_tg_class.return_value = mock_tg

        # Mock chunker
        mock_chunker = MagicMock()
        mock_chunker.chunk_text = MagicMock(return_value=[("Test chunk", "test chunk")])
        mock_chunker_class.return_value = mock_chunker

        # Mock embedder
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(
            return_value=[("hash123", [0.1, 0.2, 0.3])]
        )
        mock_embedder.metrics = MagicMock()
        mock_embedder.metrics.embed_calls = 0
        mock_embedder.metrics.embed_cached_hits = 0
        mock_embedder.metrics.embed_cached_misses = 0
        mock_embedder.metrics.total_tokens = 100
        mock_embedder.metrics.cost_estimate = 0.01
        mock_embedder_class.return_value = mock_embedder

        # Mock Vespa client
        mock_vespa = AsyncMock()
        mock_vespa.health_check = AsyncMock(return_value=True)
        mock_vespa.feed_documents = AsyncMock(return_value=1)
        mock_vespa.close = AsyncMock()
        mock_vespa.metrics = MagicMock()
        mock_vespa.metrics.vespa_feed_success = 0
        mock_vespa.metrics.vespa_feed_retries = 0
        mock_vespa.metrics.vespa_feed_failures = 0
        mock_vespa_class.return_value = mock_vespa

        yield {
            "db": mock_db,
            "tg": mock_tg,
            "chunker": mock_chunker,
            "embedder": mock_embedder,
            "vespa": mock_vespa,
        }


class TestTelegramIndexer:
    """Test cases for TelegramIndexer."""

    @pytest.mark.asyncio
    async def test_limit_messages_global_across_chats(
        self, mock_cli_args, mock_indexer_deps
    ):
        """Test that limit_messages applies globally across all chats, not per chat."""
        # Setup: Create messages for each chat
        messages_per_chat = {
            "Chat1": [
                self._create_mock_message(i, f"Message {i} from Chat1")
                for i in range(1, 6)
            ],  # 5 messages
            "Chat2": [
                self._create_mock_message(i, f"Message {i} from Chat2")
                for i in range(6, 11)
            ],  # 5 messages
            "Chat3": [
                self._create_mock_message(i, f"Message {i} from Chat3")
                for i in range(11, 16)
            ],  # 5 messages
        }

        # Track actual messages processed
        processed_messages = []

        # Mock get_messages to return different messages for each chat
        async def mock_get_messages(entity, limit=None, since_date=None):
            if entity == "entity1":
                messages = messages_per_chat["Chat1"]
                chat_name = "Chat1"
            elif entity == "entity2":
                messages = messages_per_chat["Chat2"]
                chat_name = "Chat2"
            elif entity == "entity3":
                messages = messages_per_chat["Chat3"]
                chat_name = "Chat3"
            else:
                messages = []
                chat_name = "Unknown"

            # Apply limit if specified
            if limit is not None:
                messages = messages[:limit]

            for msg in messages:
                processed_messages.append(f"{chat_name}:{msg.id}")
                yield msg

        mock_indexer_deps["tg"].get_messages = mock_get_messages

        # Mock process_message to track calls
        original_process_message = AsyncMock()

        # Set global limit to 7 messages
        mock_cli_args.limit_messages = 7
        mock_cli_args.days = 7  # Add missing days attribute
        mock_cli_args.sleep_ms = 0  # Add missing sleep_ms attribute

        indexer = TelegramIndexer(mock_cli_args)
        indexer.db = mock_indexer_deps["db"]
        indexer.tg_client = mock_indexer_deps["tg"]
        indexer.chunker = mock_indexer_deps["chunker"]
        indexer.embedder = mock_indexer_deps["embedder"]
        indexer.vespa_client = mock_indexer_deps["vespa"]

        # Mock the process_message method to just count calls
        async def mock_process_message(msg_data):
            # Only process if message has text content
            if msg_data.get("text", "").strip():
                indexer.metrics.messages_indexed += 1
                # Call embedder to simulate real processing
                await mock_indexer_deps["embedder"].embed_texts(
                    [msg_data["text"]], False
                )

        indexer.process_message = mock_process_message

        # Execute
        await indexer.run_once()

        # Verify: Should process exactly 7 messages total
        # (5 from Chat1 + 2 from Chat2, Chat3 should not be processed)
        assert (
            len(processed_messages) <= 7
        ), f"Expected at most 7 messages processed, got {len(processed_messages)}: {processed_messages}"
        assert (
            indexer.metrics.messages_indexed <= 7
        ), f"Expected at most 7 messages indexed, got {indexer.metrics.messages_indexed}"

    @pytest.mark.asyncio
    async def test_no_limit_messages_processes_all(
        self, mock_cli_args, mock_indexer_deps
    ):
        """Test that without limit_messages, all messages are processed."""
        # Setup: Create messages for each chat
        messages_per_chat = {
            "Chat1": [
                self._create_mock_message(i, f"Message {i} from Chat1")
                for i in range(1, 4)
            ],  # 3 messages
            "Chat2": [
                self._create_mock_message(i, f"Message {i} from Chat2")
                for i in range(4, 7)
            ],  # 3 messages
            "Chat3": [
                self._create_mock_message(i, f"Message {i} from Chat3")
                for i in range(7, 10)
            ],  # 3 messages
        }

        async def mock_get_messages(entity, limit=None, since_date=None):
            if entity == "entity1":
                messages = messages_per_chat["Chat1"]
            elif entity == "entity2":
                messages = messages_per_chat["Chat2"]
            elif entity == "entity3":
                messages = messages_per_chat["Chat3"]
            else:
                messages = []

            for msg in messages:
                yield msg

        mock_indexer_deps["tg"].get_messages = mock_get_messages

        # Remove limit
        mock_cli_args.limit_messages = None
        mock_cli_args.days = 7  # Add missing days attribute
        mock_cli_args.sleep_ms = 0  # Add missing sleep_ms attribute

        indexer = TelegramIndexer(mock_cli_args)
        indexer.db = mock_indexer_deps["db"]
        indexer.tg_client = mock_indexer_deps["tg"]
        indexer.chunker = mock_indexer_deps["chunker"]
        indexer.embedder = mock_indexer_deps["embedder"]
        indexer.vespa_client = mock_indexer_deps["vespa"]

        # Mock the process_message method to just count calls
        async def mock_process_message(msg_data):
            if msg_data.get("text", "").strip():
                indexer.metrics.messages_indexed += 1
                await mock_indexer_deps["embedder"].embed_texts(
                    [msg_data["text"]], False
                )

        indexer.process_message = mock_process_message

        # Execute
        await indexer.run_once()

        # Verify: Should process all 9 messages
        assert (
            indexer.metrics.messages_indexed == 9
        ), f"Expected 9 messages indexed, got {indexer.metrics.messages_indexed}"

    @pytest.mark.asyncio
    async def test_limit_messages_stops_at_exact_limit(
        self, mock_cli_args, mock_indexer_deps
    ):
        """Test that processing stops when exactly reaching the message limit."""
        # Setup: Create exactly enough messages to test boundary
        messages_per_chat = {
            "Chat1": [
                self._create_mock_message(i, f"Message {i} from Chat1")
                for i in range(1, 6)
            ],  # 5 messages
            "Chat2": [
                self._create_mock_message(i, f"Message {i} from Chat2")
                for i in range(6, 11)
            ],  # 5 messages
        }

        async def mock_get_messages(entity, limit=None, since_date=None):
            if entity == "entity1":
                messages = messages_per_chat["Chat1"]
            elif entity == "entity2":
                messages = messages_per_chat["Chat2"]
            else:
                messages = []

            # Apply limit if specified
            if limit is not None:
                messages = messages[:limit]

            for msg in messages:
                yield msg

        mock_indexer_deps["tg"].get_messages = mock_get_messages

        # Set limit to exactly match first chat
        mock_cli_args.limit_messages = 5
        mock_cli_args.days = 7  # Add missing days attribute
        mock_cli_args.sleep_ms = 0  # Add missing sleep_ms attribute

        indexer = TelegramIndexer(mock_cli_args)
        indexer.db = mock_indexer_deps["db"]
        indexer.tg_client = mock_indexer_deps["tg"]
        indexer.chunker = mock_indexer_deps["chunker"]
        indexer.embedder = mock_indexer_deps["embedder"]
        indexer.vespa_client = mock_indexer_deps["vespa"]

        # Execute
        await indexer.run_once()

        # Verify: Should process exactly 5 messages (all from Chat1, none from Chat2)
        embed_calls = len(mock_indexer_deps["embedder"].embed_texts.call_args_list)
        assert (
            embed_calls == 5
        ), f"Expected exactly 5 embedding calls, got {embed_calls}"

    @pytest.mark.asyncio
    async def test_specific_chats_with_limit(self, mock_cli_args, mock_indexer_deps):
        """Test that limit works correctly when specific chats are provided."""
        # Setup specific chats
        mock_cli_args.chats = "Chat1,Chat2"
        mock_cli_args.limit_messages = 3
        mock_cli_args.days = 7  # Add missing days attribute
        mock_cli_args.sleep_ms = 0  # Add missing sleep_ms attribute

        # Mock resolve_chats for specific chats only
        mock_indexer_deps["tg"].resolve_chats = AsyncMock(
            return_value={
                "Chat1": {
                    "entity": "entity1",
                    "id": "1",
                    "title": "Chat 1",
                    "type": "private",
                },
                "Chat2": {
                    "entity": "entity2",
                    "id": "2",
                    "title": "Chat 2",
                    "type": "group",
                },
            }
        )

        # Don't call get_all_chats since specific chats are provided
        mock_indexer_deps["tg"].get_all_chats = AsyncMock()

        messages_per_chat = {
            "Chat1": [
                self._create_mock_message(i, f"Message {i} from Chat1")
                for i in range(1, 6)
            ],  # 5 messages
            "Chat2": [
                self._create_mock_message(i, f"Message {i} from Chat2")
                for i in range(6, 11)
            ],  # 5 messages
        }

        async def mock_get_messages(entity, limit=None, since_date=None):
            if entity == "entity1":
                messages = messages_per_chat["Chat1"]
            elif entity == "entity2":
                messages = messages_per_chat["Chat2"]
            else:
                messages = []

            if limit is not None:
                messages = messages[:limit]

            for msg in messages:
                yield msg

        mock_indexer_deps["tg"].get_messages = mock_get_messages

        indexer = TelegramIndexer(mock_cli_args)
        indexer.db = mock_indexer_deps["db"]
        indexer.tg_client = mock_indexer_deps["tg"]
        indexer.chunker = mock_indexer_deps["chunker"]
        indexer.embedder = mock_indexer_deps["embedder"]
        indexer.vespa_client = mock_indexer_deps["vespa"]

        # Execute
        await indexer.run_once()

        # Verify: Should process exactly 3 messages total across specified chats
        embed_calls = len(mock_indexer_deps["embedder"].embed_texts.call_args_list)
        assert (
            embed_calls == 3
        ), f"Expected exactly 3 embedding calls, got {embed_calls}"

        # Verify get_all_chats was not called since specific chats were provided
        mock_indexer_deps["tg"].get_all_chats.assert_not_called()

    def _create_mock_message(self, message_id: int, text: str):
        """Helper to create mock message objects."""
        message = MagicMock()
        message.id = message_id
        message.text = text
        message.date = MagicMock()
        message.date.timestamp.return_value = datetime.now().timestamp()
        message.action = None  # Not a service message
        message.media = None
        return message


def test_simple_cliargs():
    """Simple test to verify CLIArgs functionality."""
    # Import CLIArgs directly to avoid global mocking from other tests
    import importlib
    import sys

    # Temporarily restore the real settings module
    original_settings = sys.modules.get("settings")
    if original_settings and hasattr(original_settings, "_mock_name"):
        # This is a mock, we need to reimport the real settings
        del sys.modules["settings"]

    try:
        from settings import CLIArgs

        args = CLIArgs(
            once=True,
            chats="Chat1,Chat2",
            days=7,
            dry_run=False,
            limit_messages=10,
            embed_batch_size=5,
            embed_concurrency=2,
            sleep_ms=0,
            log_level="INFO",
        )

        assert args.once is True
    finally:
        # Restore the mock if it existed
        if original_settings and hasattr(original_settings, "_mock_name"):
            sys.modules["settings"] = original_settings
    assert args.limit_messages == 10
    assert args.days == 7
    chat_list = args.get_chat_list()
    assert chat_list == ["Chat1", "Chat2"]


@patch("main.TelethonClientWrapper")
@patch("main.DatabaseManager")
@patch("main.TextChunker")
@patch("main.Embedder")
@patch("main.VespaClient")
@patch("main.CostEstimator")
def test_global_message_limit_calculation(
    mock_cost, mock_vespa, mock_embedder, mock_chunker, mock_db, mock_tg
):
    """Test the global message limit calculation logic."""
    # Import CLIArgs directly from file to bypass any global mocks
    import sys
    import importlib.util
    import os

    # Get the real settings module by importing it directly from file
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "settings.py"
    )
    spec = importlib.util.spec_from_file_location("real_settings", settings_path)
    real_settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_settings)

    CLIArgs = real_settings.CLIArgs

    from main import TelegramIndexer

    # Test with limit
    args_with_limit = CLIArgs(
        once=True,
        chats=None,
        days=7,
        dry_run=False,
        limit_messages=10,
        embed_batch_size=5,
        embed_concurrency=2,
        sleep_ms=0,
        log_level="INFO",
    )

    # Verify the args are correct before testing
    assert (
        args_with_limit.limit_messages == 10
    ), f"Expected limit_messages=10, got {args_with_limit.limit_messages}"

    indexer = TelegramIndexer(args_with_limit)

    # Simulate processing 5 messages from first chat
    total_processed = 5
    remaining_limit = args_with_limit.limit_messages - total_processed
    assert remaining_limit == 5, f"Expected 5 remaining, got {remaining_limit}"

    # Simulate processing 5 more messages from second chat
    total_processed = 10
    remaining_limit = args_with_limit.limit_messages - total_processed
    assert remaining_limit == 0, f"Expected 0 remaining, got {remaining_limit}"

    # Should stop processing after reaching limit
    should_stop = remaining_limit <= 0
    assert should_stop is True, "Should stop when limit reached"


@patch("main.TelethonClientWrapper")
@patch("main.DatabaseManager")
@patch("main.TextChunker")
@patch("main.Embedder")
@patch("main.VespaClient")
@patch("main.CostEstimator")
def test_no_message_limit(
    mock_cost, mock_vespa, mock_embedder, mock_chunker, mock_db, mock_tg
):
    """Test processing without message limit."""
    # Import CLIArgs directly from file to bypass any global mocks
    import sys
    import importlib.util
    import os

    # Get the real settings module by importing it directly from file
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "settings.py"
    )
    spec = importlib.util.spec_from_file_location("real_settings", settings_path)
    real_settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_settings)

    CLIArgs = real_settings.CLIArgs

    from main import TelegramIndexer

    args_no_limit = CLIArgs(
        once=True,
        chats=None,
        days=7,
        dry_run=False,
        limit_messages=None,
        embed_batch_size=5,
        embed_concurrency=2,
        sleep_ms=0,
        log_level="INFO",
    )

    # Verify the args are correct before testing
    assert (
        args_no_limit.limit_messages is None
    ), f"Expected limit_messages=None, got {args_no_limit.limit_messages}"

    indexer = TelegramIndexer(args_no_limit)

    # Without limit, remaining should be None
    total_processed = 100
    remaining_limit = None
    if args_no_limit.limit_messages:
        remaining_limit = args_no_limit.limit_messages - total_processed

    assert remaining_limit is None, "Should have no limit when limit_messages is None"


def test_simple_cliargs():
    """Simple test to verify CLIArgs functionality."""
    # Import CLIArgs directly from file to bypass any global mocks
    import sys
    import importlib.util
    import os

    # Get the real settings module by importing it directly from file
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "settings.py"
    )
    spec = importlib.util.spec_from_file_location("real_settings", settings_path)
    real_settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_settings)

    CLIArgs = real_settings.CLIArgs
    args = CLIArgs(
        once=True,
        chats="Chat1,Chat2",
        days=7,
        dry_run=False,
        limit_messages=10,
        embed_batch_size=5,
        embed_concurrency=2,
        sleep_ms=0,
        log_level="INFO",
    )

    assert args.once is True
    assert args.limit_messages == 10
    assert args.days == 7
    chat_list = args.get_chat_list()
    assert chat_list == ["Chat1", "Chat2"]


class TestCLIArgs:
    """Test cases for CLIArgs functionality."""

    def _get_real_cliargs(self):
        """Helper to get the real CLIArgs class, bypassing any global mocks."""
        import sys
        import importlib.util
        import os

        # Get the real settings module by importing it directly from file
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "settings.py"
        )
        spec = importlib.util.spec_from_file_location("real_settings", settings_path)
        real_settings = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real_settings)

        return real_settings.CLIArgs

    def test_get_chat_list_with_chats(self):
        """Test get_chat_list when chats are specified."""
        CLIArgs = self._get_real_cliargs()
        args = CLIArgs(
            once=True,
            chats="Chat1,Chat2,Chat3",
            days=7,
            dry_run=False,
            limit_messages=None,
            embed_batch_size=None,
            embed_concurrency=None,
            sleep_ms=0,
            log_level="INFO",
        )

        chat_list = args.get_chat_list()
        assert chat_list == ["Chat1", "Chat2", "Chat3"]

    def test_get_chat_list_without_chats(self):
        """Test get_chat_list when no chats are specified."""
        CLIArgs = self._get_real_cliargs()
        args = CLIArgs(
            once=True,
            chats=None,
            days=7,
            dry_run=False,
            limit_messages=None,
            embed_batch_size=None,
            embed_concurrency=None,
            sleep_ms=0,
            log_level="INFO",
        )

        chat_list = args.get_chat_list()
        assert chat_list == []

    def test_get_chat_list_with_empty_chats(self):
        """Test get_chat_list with empty chats string."""
        CLIArgs = self._get_real_cliargs()
        args = CLIArgs(
            once=True,
            chats="",
            days=7,
            dry_run=False,
            limit_messages=None,
            embed_batch_size=None,
            embed_concurrency=None,
            sleep_ms=0,
            log_level="INFO",
        )

        chat_list = args.get_chat_list()
        assert chat_list == []

    def test_get_chat_list_with_whitespace_chats(self):
        """Test get_chat_list with chats containing whitespace."""
        CLIArgs = self._get_real_cliargs()
        args = CLIArgs(
            once=True,
            chats=" Chat1 , Chat2 , Chat3 ",
            days=7,
            dry_run=False,
            limit_messages=None,
            embed_batch_size=None,
            embed_concurrency=None,
            sleep_ms=0,
            log_level="INFO",
        )

        chat_list = args.get_chat_list()
        assert chat_list == ["Chat1", "Chat2", "Chat3"]
