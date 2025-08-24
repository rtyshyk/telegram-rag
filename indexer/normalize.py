"""Text normalization and preprocessing."""

import re
import logging
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> Tuple[str, str, bool]:
    """
    Normalize text for indexing.
    
    Returns:
        (text, bm25_text, has_link)
    """
    if not text:
        return "", "", False
    
    # Detect links
    has_link = bool(re.search(r'https?://', text, re.IGNORECASE))
    
    # Keep original URLs for BM25 indexing (previously replaced with <URL>)
    bm25_text = re.sub(r'\s+', ' ', text).strip()
    
    # For display text, keep original but clean up whitespace
    display_text = re.sub(r'\s+', ' ', text).strip()
    
    return display_text, bm25_text, has_link


def create_header(sender: Optional[str], sender_username: Optional[str], message_date: int) -> str:
    """Create message header with date and sender."""
    # Convert epoch to formatted date
    dt = datetime.fromtimestamp(message_date)
    date_str = dt.strftime("%Y-%m-%d %H:%M")
    
    # Format sender
    if sender_username:
        sender_str = f"@{sender_username}"
    elif sender:
        sender_str = sender
    else:
        sender_str = "Unknown"
    
    return f"[{date_str} • {sender_str}]"


def compose_message_with_reply(
    main_text: str,
    reply_text: Optional[str] = None,
    max_reply_tokens: int = 120
) -> str:
    """
    Compose message with reply context.
    
    Args:
        main_text: Main message text
        reply_text: Reply context text (if any)
        max_reply_tokens: Maximum tokens for reply context
        
    Returns:
        Composed message text
    """
    if not reply_text:
        return main_text
    
    # Simple token approximation: ~4 chars per token
    max_reply_chars = max_reply_tokens * 4
    
    if len(reply_text) > max_reply_chars:
        reply_text = reply_text[:max_reply_chars].rsplit(' ', 1)[0] + "..."
    
    return f"{reply_text}\n\n——\n\n{main_text}"


def extract_chat_type(chat) -> str:
    """Extract chat type from Telethon chat object."""
    if hasattr(chat, 'megagroup') and chat.megagroup:
        return "group"
    elif hasattr(chat, 'channel') and chat.channel:
        return "channel"
    elif hasattr(chat, 'user_id'):
        return "private"
    else:
        return "unknown"


def format_sender_name(sender) -> Tuple[Optional[str], Optional[str]]:
    """Format sender name and username from Telethon user object."""
    if not sender:
        return None, None
    
    # Get full name
    full_name = None
    if hasattr(sender, 'first_name') and sender.first_name:
        full_name = sender.first_name
        if hasattr(sender, 'last_name') and sender.last_name:
            full_name += f" {sender.last_name}"
    
    # Get username
    username = None
    if hasattr(sender, 'username') and sender.username:
        username = sender.username
    
    return full_name, username
