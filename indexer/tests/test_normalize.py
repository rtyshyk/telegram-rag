"""Tests for text normalization utilities."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from normalize import (
    normalize_text,
    create_header,
    compose_message_with_reply,
    extract_chat_type,
    format_sender_name,
)


class TestNormalizeText:
    """Test normalize_text function."""

    def test_normalize_empty_text(self):
        """Test normalizing empty text."""
        text, bm25_text, has_link = normalize_text("")
        assert text == ""
        assert bm25_text == ""
        assert has_link is False

    def test_normalize_simple_text(self):
        """Test normalizing simple text without links."""
        input_text = "This is a simple text message."
        text, bm25_text, has_link = normalize_text(input_text)
        assert text == input_text
        assert bm25_text == input_text
        assert has_link is False

    def test_normalize_text_with_link(self):
        """Test normalizing text with HTTP link."""
        input_text = "Check out http://example.com for more info."
        text, bm25_text, has_link = normalize_text(input_text)
        assert text == input_text  # Original text preserved
        assert bm25_text == input_text
        assert has_link is True

    def test_normalize_text_with_https_link(self):
        """Test normalizing text with HTTPS link."""
        input_text = "Visit https://secure-site.com/path?query=value"
        text, bm25_text, has_link = normalize_text(input_text)
        assert text == input_text
        assert bm25_text == input_text
        assert has_link is True

    def test_normalize_text_with_multiple_links(self):
        """Test normalizing text with multiple links."""
        input_text = "First http://site1.com and second https://site2.com links."
        text, bm25_text, has_link = normalize_text(input_text)
        assert text == input_text
        assert bm25_text == input_text
        assert has_link is True

    def test_normalize_text_case_insensitive_links(self):
        """Test that link detection is case insensitive."""
        input_text = "Visit HTTP://EXAMPLE.COM and HTTPS://TEST.COM"
        text, bm25_text, has_link = normalize_text(input_text)
        assert has_link is True
        assert "HTTP://EXAMPLE.COM" in bm25_text

    def test_normalize_whitespace_cleanup(self):
        """Test whitespace normalization."""
        input_text = "Text   with    multiple     spaces\n\nand  newlines"
        text, bm25_text, has_link = normalize_text(input_text)
        assert "  " not in text  # No double spaces
        assert "  " not in bm25_text
        assert has_link is False

    def test_normalize_text_with_link_and_whitespace(self):
        """Test normalization with both links and whitespace issues."""
        input_text = "Check   http://example.com   for    info"
        text, bm25_text, has_link = normalize_text(input_text)
        assert text == "Check http://example.com for info"
        assert bm25_text == "Check http://example.com for info"
        assert has_link is True

    def test_normalize_complex_urls(self):
        """Test normalization with complex URLs."""
        input_text = (
            "Link: https://example.com/path/to/page?param1=value1&param2=value2#section"
        )
        text, bm25_text, has_link = normalize_text(input_text)
        assert has_link is True
        assert bm25_text == input_text


class TestCreateHeader:
    """Test create_header function."""

    def test_create_header_with_username(self):
        """Test header creation with username."""
        timestamp = int(datetime(2025, 1, 1, 12, 0, 0).timestamp())
        header = create_header("John Doe", "johndoe", timestamp)
        assert "@johndoe" in header
        assert "2025-01-01 12:00" in header

    def test_create_header_with_name_only(self):
        """Test header creation with name but no username."""
        timestamp = int(datetime(2025, 1, 1, 12, 0, 0).timestamp())
        header = create_header("John Doe", None, timestamp)
        assert "John Doe" in header
        assert "2025-01-01 12:00" in header

    def test_create_header_with_username_only(self):
        """Test header creation with username but no name."""
        timestamp = int(datetime(2025, 1, 1, 12, 0, 0).timestamp())
        header = create_header(None, "johndoe", timestamp)
        assert "@johndoe" in header
        assert "2025-01-01 12:00" in header

    def test_create_header_unknown_sender(self):
        """Test header creation with no sender info."""
        timestamp = int(datetime(2025, 1, 1, 12, 0, 0).timestamp())
        header = create_header(None, None, timestamp)
        assert "Unknown" in header
        assert "2025-01-01 12:00" in header

    def test_create_header_timestamp_formatting(self):
        """Test various timestamp formats."""
        timestamps = [
            int(datetime(2025, 1, 1, 0, 0, 0).timestamp()),
            int(datetime(2025, 12, 31, 23, 59, 59).timestamp()),
            int(datetime(2025, 6, 15, 12, 30, 0).timestamp()),
        ]

        for timestamp in timestamps:
            header = create_header("Test", "test", timestamp)
            assert "@test" in header  # Username is used when present
            assert "2025-" in header  # Year should be present


class TestComposeMessageWithReply:
    """Test compose_message_with_reply function."""

    def test_compose_without_reply(self):
        """Test composing message without reply."""
        result = compose_message_with_reply("Main message", None)
        assert result == "Main message"

    def test_compose_with_short_reply(self):
        """Test composing message with short reply."""
        main_text = "Main message"
        reply_text = "Short reply"
        result = compose_message_with_reply(main_text, reply_text)
        assert "Short reply" in result
        assert "Main message" in result
        assert "——" in result  # Separator should be present

    def test_compose_with_long_reply(self):
        """Test composing message with long reply that gets truncated."""
        main_text = "Main message"
        reply_text = "This is a very long reply " * 10  # Long text
        result = compose_message_with_reply(main_text, reply_text, max_reply_tokens=5)
        assert "Main message" in result
        assert len(result) < len(main_text + reply_text)  # Should be truncated

    def test_compose_reply_truncation_at_word_boundary(self):
        """Test that reply truncation happens at word boundaries."""
        main_text = "Main message."
        reply_text = "Word1 Word2 Word3 Word4 Word5 Word6 Word7 Word8"

        result = compose_message_with_reply(main_text, reply_text, max_reply_tokens=5)

        # Should preserve word boundaries in truncation
        assert "Word1" in result
        assert "Main message" in result

    def test_compose_empty_reply(self):
        """Test composing with empty reply."""
        result = compose_message_with_reply("Main message", "")
        assert result == "Main message"

    def test_compose_none_reply(self):
        """Test composing with None reply."""
        result = compose_message_with_reply("Main message", None)
        assert result == "Main message"


class TestExtractChatType:
    """Test extract_chat_type function."""

    def test_extract_megagroup(self):
        """Test extracting megagroup chat type."""
        chat = MagicMock()
        chat.megagroup = True
        chat.channel = False
        chat.user_id = None

        chat_type = extract_chat_type(chat)
        assert chat_type == "group"

    def test_extract_channel(self):
        """Test extracting channel chat type."""
        chat = MagicMock()
        chat.megagroup = False
        chat.channel = True
        chat.user_id = None

        chat_type = extract_chat_type(chat)
        assert chat_type == "channel"

    def test_extract_private_chat(self):
        """Test extracting private chat type."""
        chat = MagicMock()
        chat.megagroup = False
        chat.channel = False
        chat.user_id = 12345

        chat_type = extract_chat_type(chat)
        assert chat_type == "private"

    def test_extract_unknown_chat(self):
        """Test extracting unknown chat type."""
        chat = MagicMock()
        chat.megagroup = False
        chat.channel = False
        chat.user_id = None

        chat_type = extract_chat_type(chat)
        assert chat_type == "private"

    def test_extract_chat_without_attributes(self):
        """Test extracting chat type when attributes are missing."""
        chat = MagicMock()
        del chat.megagroup
        del chat.channel
        del chat.user_id

        chat_type = extract_chat_type(chat)
        assert chat_type == "unknown"  # Default fallback


class TestFormatSenderName:
    """Test format_sender_name function."""

    def test_format_full_name(self):
        """Test formatting sender with full name."""
        sender = MagicMock()
        sender.first_name = "John"
        sender.last_name = "Doe"
        sender.username = "johndoe"

        full_name, username = format_sender_name(sender)
        assert full_name == "John Doe"
        assert username == "johndoe"

    def test_format_first_name_only(self):
        """Test formatting sender with first name only."""
        sender = MagicMock()
        sender.first_name = "John"
        sender.last_name = None
        sender.username = "johndoe"

        full_name, username = format_sender_name(sender)
        assert full_name == "John"
        assert username == "johndoe"

    def test_format_no_name_with_username(self):
        """Test formatting sender with no name but username."""
        sender = MagicMock()
        sender.first_name = None
        sender.last_name = None
        sender.username = "johndoe"

        full_name, username = format_sender_name(sender)
        assert full_name is None
        assert username == "johndoe"

    def test_format_no_username(self):
        """Test formatting sender with no username."""
        sender = MagicMock()
        sender.first_name = "John"
        sender.last_name = "Doe"
        sender.username = None

        full_name, username = format_sender_name(sender)
        assert full_name == "John Doe"
        assert username is None

    def test_format_no_sender(self):
        """Test formatting with no sender."""
        full_name, username = format_sender_name(None)
        assert full_name is None
        assert username is None

    def test_format_sender_without_attributes(self):
        """Test formatting sender without expected attributes."""
        sender = MagicMock()
        del sender.first_name
        del sender.last_name
        del sender.username

        full_name, username = format_sender_name(sender)
        assert full_name is None
        assert username is None

    def test_format_empty_names(self):
        """Test formatting sender with empty name fields."""
        sender = MagicMock()
        sender.first_name = ""
        sender.last_name = ""
        sender.username = ""

        full_name, username = format_sender_name(sender)
        assert full_name is None
        assert username is None
