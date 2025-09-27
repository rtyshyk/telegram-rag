"""Telethon client wrapper."""

import asyncio
import logging
from typing import List, Optional, Dict, AsyncGenerator, Any
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.types import (
    User,
    Chat,
    Channel,
    Message,
    PeerUser,
    PeerChat,
    PeerChannel,
    MessageActionChatDeleteUser,
    MessageActionChatAddUser,
)
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from settings import settings
from normalize import format_sender_name, extract_chat_type

logger = logging.getLogger(__name__)


class TelethonClientWrapper:
    """Wrapper for Telethon client with helper methods."""

    def __init__(self):
        self.client = TelegramClient(
            settings.telethon_session_path, settings.tg_api_id, settings.tg_api_hash
        )
        self.me: Optional[User] = None

    async def start(self):
        """Start Telethon client and authenticate."""
        if settings.telethon_stub:
            logger.info("Using Telethon stub mode")
            return

        await self.client.start(phone=settings.tg_phone)
        self.me = await self.client.get_me()
        logger.info(
            f"Connected as {self.me.first_name} (@{self.me.username or 'no_username'})"
        )

    async def stop(self):
        """Stop Telethon client."""
        if not settings.telethon_stub:
            await self.client.disconnect()

    async def resolve_chats(self, chat_names: List[str]) -> Dict[str, Any]:
        """
        Resolve chat names/IDs to entities.

        Args:
            chat_names: List of chat names, usernames, or IDs. Special: "<Saved Messages>"

        Returns:
            Dict mapping original name to resolved entity info
        """
        if settings.telethon_stub:
            return self._stub_resolve_chats(chat_names)

        resolved = {}

        for name in chat_names:
            try:
                if name == "<Saved Messages>":
                    # Saved Messages is a special chat with yourself
                    entity = self.me
                    resolved[name] = {
                        "entity": entity,
                        "id": str(self.me.id),
                        "title": "Saved Messages",
                        "type": "saved",
                        "username": getattr(entity, "username", None),
                    }
                else:
                    # Try to resolve by username, name, or ID
                    if name.isdigit():
                        entity = await self.client.get_entity(int(name))
                    else:
                        entity = await self.client.get_entity(name)

                    # Get chat info
                    chat_type = extract_chat_type(entity)
                    title = getattr(entity, "title", None) or getattr(
                        entity, "first_name", name
                    )

                    resolved[name] = {
                        "entity": entity,
                        "id": str(entity.id),
                        "title": title,
                        "type": chat_type,
                        "username": getattr(entity, "username", None),
                    }

                logger.info(
                    f"Resolved '{name}' -> {resolved[name]['title']} ({resolved[name]['type']})"
                )

            except Exception as e:
                logger.error(f"Failed to resolve chat '{name}': {e}")
                resolved[name] = {"error": str(e)}

        return resolved

    async def get_all_chats(self) -> List[str]:
        """
        Get all available chats/dialogs for the user.

        Returns:
            List of chat names that can be used with resolve_chats()
        """
        if settings.telethon_stub:
            return ["<Saved Messages>", "Test Chat 1", "Test Chat 2"]

        chat_names = []

        try:
            # Get all dialogs (conversations)
            async for dialog in self.client.iter_dialogs():
                if dialog.entity:
                    chat_name = None
                    # Get entity title/name
                    if hasattr(dialog.entity, "title") and dialog.entity.title:
                        # Group/Channel
                        chat_name = dialog.entity.title
                    elif (
                        hasattr(dialog.entity, "first_name")
                        and dialog.entity.first_name
                    ):
                        # User
                        name = dialog.entity.first_name
                        if (
                            hasattr(dialog.entity, "last_name")
                            and dialog.entity.last_name
                        ):
                            name += f" {dialog.entity.last_name}"
                        chat_name = name
                    elif hasattr(dialog.entity, "username") and dialog.entity.username:
                        # Username fallback
                        chat_name = f"@{dialog.entity.username}"

                    # Only add non-empty chat names
                    if chat_name and chat_name.strip():
                        chat_names.append(chat_name.strip())

            # Always include Saved Messages
            chat_names.append("<Saved Messages>")

            logger.info(f"Found {len(chat_names)} available chats")

        except Exception as e:
            logger.error(f"Error getting all chats: {e}")
            # Fallback to at least Saved Messages
            chat_names = ["<Saved Messages>"]

        return chat_names

    async def get_messages(
        self,
        entity: Any,
        limit: Optional[int] = None,
        since_date: Optional[datetime] = None,
        reverse: bool = False,
    ) -> AsyncGenerator[Message, None]:
        """
        Get messages from a chat.

        Args:
            entity: Chat entity to fetch from
            limit: Maximum number of messages
            since_date: Only fetch messages newer than this date
            reverse: If True, fetch from oldest to newest
        """
        if settings.telethon_stub:
            async for msg in self._stub_get_messages(entity, limit, since_date):
                yield msg
            return

        try:
            kwargs = {
                "reverse": reverse,
                "wait_time": 1,  # Rate limiting
            }

            if limit:
                kwargs["limit"] = limit
            if since_date:
                kwargs["offset_date"] = since_date

            async for message in self.client.iter_messages(entity, **kwargs):
                # Skip service messages that we can't process
                if message.action:
                    continue

                # Skip if no text content
                if not message.text and not (
                    message.media and hasattr(message.media, "caption")
                ):
                    continue

                yield message

                # Rate limiting
                await asyncio.sleep(0.1)

        except FloodWaitError as e:
            logger.warning(f"Hit flood wait, sleeping for {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            raise

    async def get_message_by_id(
        self, entity: Any, message_id: int
    ) -> Optional[Message]:
        """Get a specific message by ID."""
        if settings.telethon_stub:
            return self._stub_get_message_by_id(entity, message_id)

        try:
            messages = await self.client.get_messages(entity, ids=[message_id])
            return messages[0] if messages and messages[0] else None
        except Exception as e:
            logger.warning(f"Failed to get message {message_id}: {e}")
            return None

    def extract_message_data(
        self, message: Message, chat_entity: Any
    ) -> Dict[str, Any]:
        """Extract structured data from a Telethon message."""
        # Get text content
        text = message.text or ""
        if (
            message.media
            and hasattr(message.media, "caption")
            and message.media.caption
        ):
            text = message.media.caption

        # Get sender info
        sender_name, sender_username = format_sender_name(message.sender)

        # Extract metadata
        data = {
            "message_id": message.id,
            "text": text,
            "sender": sender_name,
            "sender_username": sender_username,
            "message_date": int(message.date.timestamp()),
            "edit_date": int(message.edit_date.timestamp())
            if message.edit_date
            else None,
            "chat_type": extract_chat_type(chat_entity),
            "reply_to_msg_id": message.reply_to_msg_id,
            "thread_id": getattr(message, "thread_id", None),
            "forward_from": None,
        }

        # Handle forwards
        if message.forward:
            if message.forward.from_name:
                data["forward_from"] = message.forward.from_name
            elif message.forward.sender:
                forward_name, _ = format_sender_name(message.forward.sender)
                data["forward_from"] = forward_name

        data["entity"] = chat_entity
        return data

    def _stub_resolve_chats(self, chat_names: List[str]) -> Dict[str, Any]:
        """Stub implementation for testing."""
        resolved = {}
        for i, name in enumerate(chat_names):
            resolved[name] = {
                "entity": f"stub_entity_{i}",
                "id": str(1000 + i),
                "title": f"Test {name}",
                "type": "private" if name == "<Saved Messages>" else "group",
                "username": f"test_chat_{i}" if name != "<Saved Messages>" else None,
            }
        return resolved

    async def _stub_get_messages(
        self, entity: Any, limit: Optional[int], since_date: Optional[datetime]
    ) -> AsyncGenerator[Any, None]:
        """Stub implementation for testing."""
        # Generate fake messages
        count = min(limit or 10, 10)
        for i in range(count):
            message = type(
                "Message",
                (),
                {
                    "id": 1000 + i,
                    "text": f"Test message {i} content",
                    "sender": type(
                        "User",
                        (),
                        {"first_name": "Test", "username": "testuser", "id": 12345},
                    )(),
                    "date": datetime.now() - timedelta(days=i),
                    "edit_date": None,
                    "reply_to_msg_id": None,
                    "forward": None,
                    "action": None,
                    "media": None,
                },
            )()
            yield message
            await asyncio.sleep(0.01)

    def _stub_get_message_by_id(self, entity: Any, message_id: int) -> Optional[Any]:
        """Stub implementation for testing."""
        return type(
            "Message",
            (),
            {
                "id": message_id,
                "text": f"Reply context for message {message_id}",
                "date": datetime.now(),
                "edit_date": None,
            },
        )()
