"""State management helpers for resumable indexing."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


@dataclass
class BackfillRecord:
    """Progress record for a single chat."""

    chat_id: str
    last_message_id: int
    updated_at: str


class BackfillStateStore:
    """Persist per-chat backfill progress to a JSON file."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._state: Dict[str, BackfillRecord] = {}
        self._loaded = False

    async def load(self) -> None:
        """Load state from disk if present."""
        if self._loaded:
            return

        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._loaded = True
            return

        try:
            content = await asyncio.to_thread(self.path.read_text)
            data = json.loads(content)
            chats = data.get("chats", {}) if isinstance(data, dict) else {}
            for chat_id, record in chats.items():
                last_message_id = int(record.get("last_message_id", 0))
                updated_at = str(record.get("updated_at", _now_iso()))
                self._state[chat_id] = BackfillRecord(
                    chat_id=chat_id,
                    last_message_id=last_message_id,
                    updated_at=updated_at,
                )
        except FileNotFoundError:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        finally:
            self._loaded = True

    async def get_last_message_id(self, chat_id: str) -> Optional[int]:
        """Return the last processed message ID for a chat."""
        await self.load()
        record = self._state.get(chat_id)
        return record.last_message_id if record else None

    async def update_chat(self, chat_id: str, message_id: int) -> None:
        """Persist progress for a chat."""
        await self.load()

        async with self._lock:
            existing = self._state.get(chat_id)
            if existing and existing.last_message_id >= message_id:
                # No progress to persist.
                return

            record = BackfillRecord(
                chat_id=chat_id,
                last_message_id=message_id,
                updated_at=_now_iso(),
            )
            self._state[chat_id] = record
            await self._persist()

    async def snapshot(self) -> Dict[str, BackfillRecord]:
        """Return a copy of the in-memory state."""
        await self.load()
        return dict(self._state)

    async def _persist(self) -> None:
        payload = {
            "chats": {
                chat_id: {
                    "last_message_id": record.last_message_id,
                    "updated_at": record.updated_at,
                }
                for chat_id, record in self._state.items()
            }
        }

        content = json.dumps(payload, indent=2, sort_keys=True)
        await asyncio.to_thread(self.path.write_text, content)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
