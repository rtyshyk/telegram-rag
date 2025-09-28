#!/usr/bin/env python3
"""
Telegram RAG Indexer - Phase 2 Implementation

Indexes Telegram messages with embedding and chunking.
"""

import asyncio
import argparse
import logging
import sys
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
import hashlib

from telethon import events

from settings import settings, CLIArgs
from db import DatabaseManager
from telethon_client import TelethonClientWrapper
from normalize import normalize_text, create_header, compose_message_with_reply
from chunker import TextChunker
from embedder import Embedder
from vespa_client import VespaClient
from cost import CostEstimator
from models import Chunk, VespaDocument, IndexerMetrics
from state import BackfillStateStore

logger = logging.getLogger(__name__)


class TelegramIndexer:
    """Main indexer class for processing Telegram messages."""

    def __init__(self, args: CLIArgs):
        self.args = args
        self.db = DatabaseManager(settings.database_url)
        self.tg_client = TelethonClientWrapper()
        self.chunker = TextChunker()
        self.embedder = Embedder(self.db)
        self.vespa_client = VespaClient()
        self.cost_estimator = CostEstimator()
        self.metrics = IndexerMetrics()
        self.target_chats: Dict[str, Dict[str, Any]] = {}
        self._chat_names: Dict[str, str] = {}
        self.message_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._worker_tasks: List[asyncio.Task] = []
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._lookback_lock = asyncio.Lock()
        self._event_handlers: List[Tuple[Callable, Any]] = []
        self.backfill_state = BackfillStateStore(self.args.backfill_state_path)
        worker_count = self._int_arg("daemon_worker_concurrency", 3)
        self.daemon_worker_concurrency = max(1, worker_count)
        lookback_minutes = max(0, self._int_arg("daemon_lookback_minutes", 5))
        self.lookback_window = timedelta(minutes=lookback_minutes)
        connection_secs = max(0, self._int_arg("daemon_connection_check_secs", 60))
        self.connection_check_interval = connection_secs
        lookback_limit = self._int_arg("lookback_message_limit", 250)
        self.lookback_message_limit = lookback_limit if lookback_limit > 0 else None
        self.backfill_checkpoint_interval = max(
            1, self._int_arg("backfill_checkpoint_interval", 50)
        )
        self.hourly_sweep_interval_minutes = self._int_arg(
            "hourly_sweep_interval_minutes", 60
        )
        self.hourly_sweep_days = max(0, self._int_arg("hourly_sweep_days", 7))
        self._last_connection_state = True

        # Apply CLI overrides
        if args.embed_batch_size:
            self.embedder.batch_size = args.embed_batch_size
        if args.embed_concurrency:
            self.embedder.concurrency = args.embed_concurrency

    def _int_arg(self, name: str, default: int) -> int:
        value = getattr(self.args, name, default)
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            logger.debug(
                "Invalid value for %s=%s; using default %s", name, value, default
            )
            return default

    async def initialize(self):
        """Initialize all clients and connections."""
        logger.info("Initializing indexer...")

        await self.db.initialize()
        await self.tg_client.start()

        # Check Vespa health
        if not await self.vespa_client.health_check():
            logger.warning("Vespa health check failed - documents may not be indexed")

        logger.info("Indexer initialized successfully")

    async def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up...")

        await self.tg_client.stop()
        await self.vespa_client.close()
        await self.db.close()

    async def _prepare_target_chats(
        self, mode: str
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Resolve and cache chats for the current session."""

        chat_list = self.args.get_chat_list()
        if not chat_list:
            logger.info("No specific chats provided, getting all available chats...")
            chat_list = await self.tg_client.get_all_chats()
            logger.info(f"Found {len(chat_list)} chats to process")

        logger.info(f"{mode} target chats: {', '.join(chat_list)}")

        resolved_chats = await self.tg_client.resolve_chats(chat_list)

        valid_chats: List[Tuple[str, Dict[str, Any]]] = []
        self.target_chats.clear()
        self._chat_names.clear()

        for name, info in resolved_chats.items():
            if "error" in info:
                logger.error(f"Failed to resolve '{name}': {info['error']}")
                continue

            chat_id = str(info["id"])
            cached_info = dict(info)
            cached_info["source_name"] = name
            self.target_chats[chat_id] = cached_info
            self._chat_names[chat_id] = cached_info.get("title", name)

            valid_chats.append((name, cached_info))
            logger.info(f"✓ {name} -> {cached_info['title']} ({cached_info['type']})")

        if not valid_chats:
            raise ValueError("No valid chats found")

        return valid_chats

    async def run_once(self) -> None:
        """Run one-shot indexing."""
        if self.args.days is None:
            logger.info("Starting one-shot indexing for full history")
        else:
            logger.info(f"Starting one-shot indexing for {self.args.days} days")

        valid_chats = await self._prepare_target_chats("One-shot")

        # Calculate date range (None means full history)
        if self.args.days is None:
            since_date = None
            logger.info("Fetching messages for entire available history")
        else:
            since_date = datetime.now() - timedelta(days=self.args.days)
            logger.info(
                f"Fetching messages since {since_date.strftime('%Y-%m-%d %H:%M')}"
            )

        # Process each chat with global message limit
        total_messages_processed = 0
        for chat_name, chat_info in valid_chats:
            logger.info(f"Processing chat: {chat_info['title']}")

            # Calculate remaining message limit
            remaining_limit = None
            if self.args.limit_messages:
                remaining_limit = self.args.limit_messages - total_messages_processed
                if remaining_limit <= 0:
                    logger.info(
                        f"Message limit ({self.args.limit_messages}) reached, stopping"
                    )
                    break

            processed_count = await self.process_chat(
                chat_info, since_date, remaining_limit
            )
            total_messages_processed += processed_count

        # Print final metrics
        self.print_metrics()

    async def run_daemon_mode(self) -> None:
        """Run continuous indexing with event handlers and periodic sweeps."""

        logger.info("Starting daemon indexing (near-live mode)")
        self._shutdown_event.clear()

        ordered_chats = await self._prepare_target_chats("Daemon")
        await self.backfill_state.load()

        self._start_workers()

        try:
            self._register_event_handlers()
            self._last_connection_state = self.tg_client.is_connected()

            await self._run_initial_backfill(ordered_chats)
            await self.message_queue.join()

            await self._run_recent_lookback(reason="startup")

            if self.hourly_sweep_interval_minutes > 0 and self.hourly_sweep_days > 0:
                self._background_tasks.append(
                    asyncio.create_task(self._hourly_sweep_loop())
                )
            if not settings.telethon_stub and self.connection_check_interval > 0:
                self._background_tasks.append(
                    asyncio.create_task(self._connection_watchdog())
                )

            logger.info("Daemon ready; awaiting Telegram updates")
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            raise
        finally:
            await self._cancel_background_tasks()
            await self._stop_workers()
            self._unregister_event_handlers()

    def _start_workers(self) -> None:
        if self._worker_tasks:
            return

        for idx in range(self.daemon_worker_concurrency):
            task = asyncio.create_task(self._worker_loop(idx))
            self._worker_tasks.append(task)

    async def _worker_loop(self, worker_id: int) -> None:
        try:
            while True:
                item = await self.message_queue.get()
                if item is None:
                    self.message_queue.task_done()
                    break

                try:
                    await self.process_message(item)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception(
                        "Worker %s failed to process message %s: %s",
                        worker_id,
                        item.get("message_id"),
                        exc,
                    )
                finally:
                    self.message_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _stop_workers(self) -> None:
        if not self._worker_tasks:
            return

        for _ in self._worker_tasks:
            await self.message_queue.put(None)

        for task in self._worker_tasks:
            with suppress(asyncio.CancelledError):
                await task

        self._worker_tasks.clear()

    async def _cancel_background_tasks(self) -> None:
        if not self._background_tasks:
            return

        for task in self._background_tasks:
            task.cancel()

        for task in self._background_tasks:
            with suppress(asyncio.CancelledError):
                await task

        self._background_tasks.clear()

    def _register_event_handlers(self) -> None:
        if settings.telethon_stub:
            logger.info("Telethon stub mode: skipping event handler registration")
            return

        if self._event_handlers:
            return

        chat_filters = [info["entity"] for info in self.target_chats.values()]

        new_message_builder = events.NewMessage(chats=chat_filters, incoming=True)
        self.tg_client.client.add_event_handler(
            self._on_new_message, new_message_builder
        )

        edit_builder = events.MessageEdited(chats=chat_filters)
        self.tg_client.client.add_event_handler(self._on_message_edit, edit_builder)

        self._event_handlers.extend(
            [
                (self._on_new_message, new_message_builder),
                (self._on_message_edit, edit_builder),
            ]
        )

    def _unregister_event_handlers(self) -> None:
        if not self._event_handlers or settings.telethon_stub:
            self._event_handlers.clear()
            return

        for handler, builder in self._event_handlers:
            with suppress(Exception):  # pylint: disable=broad-except
                self.tg_client.client.remove_event_handler(handler, builder)

        self._event_handlers.clear()

    async def _on_new_message(self, event) -> None:  # type: ignore[override]
        await self._handle_event_message(event, is_edit=False)

    async def _on_message_edit(self, event) -> None:  # type: ignore[override]
        await self._handle_event_message(event, is_edit=True)

    async def _handle_event_message(self, event, *, is_edit: bool) -> None:
        if self._shutdown_event.is_set():
            return

        try:
            chat_id = getattr(event, "chat_id", None)
            if chat_id is None:
                return

            chat_id_str = str(chat_id)
            chat_info = self.target_chats.get(chat_id_str)
            if not chat_info:
                return

            message = getattr(event, "message", None)
            if message is None or getattr(message, "action", None):
                return

            msg_data = self.tg_client.extract_message_data(message, chat_info["entity"])
            msg_data["chat_id"] = chat_id_str
            msg_data["source_title"] = chat_info.get("title")
            msg_data["chat_username"] = chat_info.get("username")
            msg_data["is_edit"] = is_edit

            await self._enqueue_message_data(msg_data)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to handle message event: %s", exc)

    async def _enqueue_message_data(self, msg_data: Dict[str, Any]) -> None:
        text = msg_data.get("text", "")
        if not text.strip():
            return

        self.metrics.messages_scanned += 1
        await self.message_queue.put(msg_data)

    async def _run_initial_backfill(
        self, ordered_chats: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        logger.info("Starting initial backfill (resumable checkpoints)")

        total_processed = 0
        remaining_limit = self.args.limit_messages

        for _, chat_info in ordered_chats:
            per_chat_limit = None
            if remaining_limit is not None:
                per_chat_limit = max(0, remaining_limit - total_processed)
                if per_chat_limit == 0:
                    logger.info(
                        "Message limit (%s) reached; stopping backfill", remaining_limit
                    )
                    break

            processed = await self._backfill_chat(chat_info, per_chat_limit)
            total_processed += processed

        logger.info(
            "Initial backfill queued %d messages for processing", total_processed
        )

    async def _backfill_chat(
        self, chat_info: Dict[str, Any], limit_messages: Optional[int]
    ) -> int:
        chat_id = str(chat_info["id"])
        resume_from = await self.backfill_state.get_last_message_id(chat_id)
        since_date: Optional[datetime] = None
        if self.args.days is not None:
            since_date = datetime.now() - timedelta(days=self.args.days)

        logger.info(
            "Backfilling %s (resume from %s)",
            chat_info.get("title"),
            resume_from or "beginning",
        )

        processed = 0
        latest_id = resume_from or 0
        checkpoint_counter = 0

        async for message in self.tg_client.get_messages(
            chat_info["entity"],
            limit=limit_messages,
            since_date=since_date,
            reverse=True,
            min_message_id=resume_from,
        ):
            msg_data = self.tg_client.extract_message_data(message, chat_info["entity"])
            msg_data["chat_id"] = chat_id
            msg_data["source_title"] = chat_info.get("title")
            msg_data["chat_username"] = chat_info.get("username")

            if not msg_data.get("text", "").strip():
                continue

            await self._enqueue_message_data(msg_data)
            processed += 1
            checkpoint_counter += 1
            latest_id = max(latest_id, msg_data.get("message_id", latest_id))

            if limit_messages is not None and processed >= limit_messages:
                break

            if checkpoint_counter >= self.backfill_checkpoint_interval:
                await self.backfill_state.update_chat(chat_id, latest_id)
                checkpoint_counter = 0

        if processed and latest_id:
            await self.backfill_state.update_chat(chat_id, latest_id)

        logger.info(
            "Backfill complete for %s (%d messages)",
            chat_info.get("title"),
            processed,
        )

        return processed

    async def _scan_chat_window(
        self,
        chat_info: Dict[str, Any],
        since_date: datetime,
        limit_messages: Optional[int],
        reason: str,
    ) -> int:
        chat_id = str(chat_info["id"])
        processed = 0

        async for message in self.tg_client.get_messages(
            chat_info["entity"],
            limit=limit_messages,
            since_date=since_date,
            reverse=True,
        ):
            msg_data = self.tg_client.extract_message_data(message, chat_info["entity"])
            msg_data["chat_id"] = chat_id
            msg_data["source_title"] = chat_info.get("title")
            msg_data["chat_username"] = chat_info.get("username")

            if not msg_data.get("text", "").strip():
                continue

            await self._enqueue_message_data(msg_data)
            processed += 1

            if limit_messages is not None and processed >= limit_messages:
                break

        if processed:
            logger.debug(
                "%s queued %d messages for %s",
                reason,
                processed,
                chat_info.get("title"),
            )

        return processed

    async def _scan_recent_history(
        self, since_date: datetime, limit_messages: Optional[int], reason: str
    ) -> int:
        total = 0
        for chat_info in self.target_chats.values():
            total += await self._scan_chat_window(
                chat_info, since_date, limit_messages, reason
            )
        return total

    async def _run_recent_lookback(self, *, reason: str) -> None:
        if self.lookback_window.total_seconds() <= 0 or not self.target_chats:
            return

        if self._lookback_lock.locked():
            logger.debug("Skipping %s look-back; another run is active", reason)
            return

        async with self._lookback_lock:
            since_date = datetime.now() - self.lookback_window
            logger.info(
                "%s look-back since %s",
                reason.capitalize(),
                since_date.strftime("%Y-%m-%d %H:%M"),
            )
            queued = await self._scan_recent_history(
                since_date, self.lookback_message_limit, f"{reason} look-back"
            )

            if queued:
                logger.info(
                    "%s look-back queued %d messages",
                    reason.capitalize(),
                    queued,
                )
                await self.message_queue.join()

    async def _connection_watchdog(self) -> None:
        if settings.telethon_stub:
            return

        try:
            previous_state = self._last_connection_state
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.connection_check_interval)
                current_state = self.tg_client.is_connected()

                if current_state and not previous_state:
                    logger.info("Telethon reconnected; running safety look-back")
                    await self._run_recent_lookback(reason="reconnect")

                previous_state = current_state
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Connection watchdog failed: %s", exc)

    async def _hourly_sweep_loop(self) -> None:
        interval_seconds = self.hourly_sweep_interval_minutes * 60
        if (
            interval_seconds <= 0
            or self.hourly_sweep_days <= 0
            or not self.target_chats
        ):
            return

        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(interval_seconds)
                if self._shutdown_event.is_set():
                    break

                since_date = datetime.now() - timedelta(days=self.hourly_sweep_days)
                logger.info(
                    "Hourly sweep: scanning last %s days",
                    self.hourly_sweep_days,
                )
                queued = await self._scan_recent_history(
                    since_date, self.lookback_message_limit, "hourly sweep"
                )
                if queued:
                    logger.info("Hourly sweep queued %d messages", queued)
                    await self.message_queue.join()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Hourly sweep loop failed: %s", exc)

    async def shutdown(self) -> None:
        if not self._shutdown_event.is_set():
            logger.info("Shutdown signal received; stopping daemon")
            self._shutdown_event.set()

    async def process_chat(
        self,
        chat_info: Dict[str, Any],
        since_date: datetime,
        limit_messages: Optional[int] = None,
    ) -> int:
        """Process all messages in a chat.

        Returns:
            Number of messages processed from this chat
        """
        chat_id = chat_info["id"]
        entity = chat_info["entity"]

        messages_processed = 0

        try:
            async for message in self.tg_client.get_messages(
                entity, limit=limit_messages, since_date=since_date
            ):
                self.metrics.messages_scanned += 1

                # Extract message data
                msg_data = self.tg_client.extract_message_data(message, entity)
                msg_data["chat_id"] = chat_id
                msg_data["source_title"] = chat_info["title"]
                msg_data["chat_username"] = chat_info.get("username")

                # Skip if no text content
                if not msg_data["text"].strip():
                    continue

                # Process the message
                await self.process_message(msg_data)
                messages_processed += 1

                # Rate limiting and progress
                if self.args.sleep_ms > 0:
                    await asyncio.sleep(self.args.sleep_ms / 1000)

                if messages_processed % 100 == 0:
                    logger.info(
                        f"Processed {messages_processed} messages from {chat_info['title']}"
                    )

        except Exception as e:
            logger.error(f"Error processing chat {chat_info['title']}: {e}")
            raise

        logger.info(
            f"Completed chat {chat_info['title']}: {messages_processed} messages processed"
        )

        return messages_processed

    async def process_message(self, msg_data: Dict[str, Any]):
        """Process a single message into chunks and index them."""
        chat_id = msg_data["chat_id"]
        message_id = msg_data["message_id"]

        # Check if we already have chunks for this message
        existing_chunks = await self.db.get_existing_chunks(chat_id, message_id)

        # If message hasn't been edited, skip reprocessing
        if existing_chunks and not self._message_needs_update(
            msg_data, existing_chunks
        ):
            logger.debug(f"Skipping unchanged message {message_id}")
            return

        # Get reply context if needed
        reply_text = None
        if msg_data.get("reply_to_msg_id"):
            reply_msg = await self.tg_client.get_message_by_id(
                msg_data.get("entity"), msg_data["reply_to_msg_id"]
            )
            if reply_msg and hasattr(reply_msg, "text"):
                reply_text = reply_msg.text

        # Normalize and compose message text
        text, bm25_text, has_link = normalize_text(msg_data["text"])
        header = create_header(
            msg_data.get("sender"),
            msg_data.get("sender_username"),
            msg_data["message_date"],
        )

        composed_text = compose_message_with_reply(
            text, reply_text, settings.reply_context_tokens
        )

        # Create chunks
        chunks = self.chunker.chunk_text(composed_text, header)

        if not chunks:
            logger.warning(f"No chunks created for message {message_id}")
            return

        # Process each chunk
        chunk_objects = []
        texts_to_embed = []

        for chunk_idx, (full_text, chunk_bm25_text) in enumerate(chunks):
            # Create chunk ID
            chunk_id = (
                f"{chat_id}:{message_id}:{chunk_idx}:v{settings.chunking_version}"
            )

            # Compute text hash for caching
            text_hash = hashlib.sha256(
                f"{full_text}|{settings.embed_model}|{settings.chunking_version}|{settings.preprocess_version}".encode()
            ).hexdigest()

            # Create chunk object
            chunk_obj = Chunk(
                chunk_id=chunk_id,
                chat_id=chat_id,
                message_id=message_id,
                chunk_idx=chunk_idx,
                text_hash=text_hash,
                message_date=msg_data["message_date"],
                edit_date=msg_data.get("edit_date"),
                sender=msg_data.get("sender"),
                sender_username=msg_data.get("sender_username"),
                chat_username=msg_data.get("chat_username"),
                chat_type=msg_data.get("chat_type"),
                thread_id=msg_data.get("thread_id"),
                has_link=has_link,
            )

            chunk_objects.append(chunk_obj)
            texts_to_embed.append(full_text)

        # Get embeddings
        embeddings = await self.embedder.embed_texts(texts_to_embed, self.args.dry_run)

        if self.args.dry_run:
            logger.info(
                f"DRY RUN: Would process {len(chunks)} chunks for message {message_id}"
            )
            return

        # Create Vespa documents
        vespa_docs = []
        for chunk_obj, (text_hash, vector) in zip(chunk_objects, embeddings):
            # Determine which vector field to use based on embedding dimensions
            vector_dict = {"values": vector}
            if settings.embed_dimensions == 1536:
                vector_small = vector_dict
                vector_large = None
            elif settings.embed_dimensions == 3072:
                vector_small = None
                vector_large = vector_dict
            else:
                raise ValueError(
                    f"Unsupported embedding dimension: {settings.embed_dimensions}. Only 1536 and 3072 are supported."
                )

            doc = VespaDocument(
                id=chunk_obj.chunk_id,
                chat_id=chunk_obj.chat_id,
                message_id=chunk_obj.message_id,
                chunk_idx=chunk_obj.chunk_idx,
                source_title=msg_data.get("source_title"),
                sender=chunk_obj.sender,
                sender_username=chunk_obj.sender_username,
                chat_username=chunk_obj.chat_username,
                chat_type=chunk_obj.chat_type,
                message_date=chunk_obj.message_date,
                edit_date=chunk_obj.edit_date,
                thread_id=chunk_obj.thread_id,
                has_link=chunk_obj.has_link,
                text=texts_to_embed[chunk_obj.chunk_idx],
                bm25_text=bm25_text,
                vector_small=vector_small,
                vector_large=vector_large,
            )
            vespa_docs.append(doc)

        # Store in database
        for chunk_obj in chunk_objects:
            await self.db.upsert_chunk(chunk_obj)

        # Feed to Vespa
        success_count = await self.vespa_client.feed_documents(vespa_docs)

        self.metrics.messages_indexed += 1
        self.metrics.chunks_written += len(chunk_objects)

        logger.debug(
            f"Processed message {message_id}: {len(chunks)} chunks, {success_count} fed to Vespa"
        )

    def _message_needs_update(
        self, msg_data: Dict[str, Any], existing_chunks: List[Chunk]
    ) -> bool:
        """Check if message needs to be reprocessed."""
        if not existing_chunks:
            return True

        # Check if edit date is newer
        edit_date = msg_data.get("edit_date")
        if edit_date:
            for chunk in existing_chunks:
                if not chunk.edit_date or edit_date > chunk.edit_date:
                    return True

        return False

    def print_metrics(self):
        """Print final processing metrics."""
        total_metrics = IndexerMetrics(
            messages_scanned=self.metrics.messages_scanned,
            messages_indexed=self.metrics.messages_indexed,
            chunks_written=self.metrics.chunks_written,
            embed_calls=self.embedder.metrics.embed_calls,
            embed_cached_hits=self.embedder.metrics.embed_cached_hits,
            embed_cached_misses=self.embedder.metrics.embed_cached_misses,
            vespa_feed_success=self.vespa_client.metrics.vespa_feed_success,
            vespa_feed_retries=self.vespa_client.metrics.vespa_feed_retries,
            vespa_feed_failures=self.vespa_client.metrics.vespa_feed_failures,
            total_tokens=self.embedder.metrics.total_tokens,
            cost_estimate=self.embedder.metrics.cost_estimate,
        )

        # Calculate cache hit rate
        total_embed_requests = (
            total_metrics.embed_cached_hits + total_metrics.embed_cached_misses
        )
        cache_hit_rate = (
            (total_metrics.embed_cached_hits / total_embed_requests * 100)
            if total_embed_requests > 0
            else 0
        )

        logger.info("=" * 60)
        logger.info("INDEXING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Messages scanned: {total_metrics.messages_scanned:,}")
        logger.info(f"Messages indexed: {total_metrics.messages_indexed:,}")
        logger.info(f"Chunks written: {total_metrics.chunks_written:,}")
        logger.info(f"Cache hit rate: {cache_hit_rate:.1f}%")
        logger.info(f"Embedding tokens: {total_metrics.total_tokens:,}")
        logger.info(f"Estimated cost: ${total_metrics.cost_estimate:.4f}")
        logger.info(
            f"Vespa feeds: {total_metrics.vespa_feed_success:,} success, {total_metrics.vespa_feed_failures:,} failures"
        )
        logger.info("=" * 60)


async def run_daemon(args: CLIArgs) -> None:
    """Run the continuous indexing daemon."""

    indexer = TelegramIndexer(args)

    try:
        await indexer.initialize()
        await indexer.run_daemon_mode()
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user")
    except Exception as exc:
        logger.error(f"Daemon failed: {exc}")
        raise
    finally:
        await indexer.shutdown()
        await indexer.cleanup()


def setup_logging(log_level: str):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> CLIArgs:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Telegram RAG Indexer")

    parser.add_argument("--once", action="store_true", help="Run one-shot indexing")
    parser.add_argument(
        "--chats",
        type=str,
        help="Comma-separated chat names/IDs (optional - defaults to all chats)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Days of history to fetch (default: entire history)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Estimate costs without calling APIs"
    )
    parser.add_argument(
        "--limit-messages", type=int, help="Limit number of messages (for testing)"
    )
    parser.add_argument(
        "--embed-batch-size", type=int, help="Override embedding batch size"
    )
    parser.add_argument(
        "--embed-concurrency", type=int, help="Override embedding concurrency"
    )
    parser.add_argument(
        "--sleep-ms", type=int, default=0, help="Sleep between messages (ms)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--daemon-lookback-minutes",
        type=int,
        default=5,
        help="Minutes of history to replay on startup/reconnect",
    )
    parser.add_argument(
        "--daemon-connection-check-secs",
        type=int,
        default=60,
        help="Seconds between connection health checks",
    )
    parser.add_argument(
        "--daemon-worker-concurrency",
        type=int,
        default=3,
        help="Number of concurrent message processing workers",
    )
    parser.add_argument(
        "--hourly-sweep-days",
        type=int,
        default=7,
        help="Days of history to re-scan each sweep",
    )
    parser.add_argument(
        "--hourly-sweep-interval-minutes",
        type=int,
        default=60,
        help="Minutes between hourly sweep iterations",
    )
    parser.add_argument(
        "--backfill-state-path",
        type=str,
        default=settings.backfill_state_path,
        help="Path to JSON file storing backfill checkpoints",
    )
    parser.add_argument(
        "--backfill-checkpoint-interval",
        type=int,
        default=50,
        help="Persist backfill progress every N messages",
    )
    parser.add_argument(
        "--lookback-message-limit",
        type=int,
        default=250,
        help="Max messages per chat when replaying recent history",
    )

    args = parser.parse_args()

    return CLIArgs(
        once=args.once,
        chats=args.chats,
        days=args.days,
        dry_run=args.dry_run,
        limit_messages=args.limit_messages,
        embed_batch_size=args.embed_batch_size,
        embed_concurrency=args.embed_concurrency,
        sleep_ms=args.sleep_ms,
        log_level=args.log_level,
        daemon_lookback_minutes=args.daemon_lookback_minutes,
        daemon_connection_check_secs=args.daemon_connection_check_secs,
        daemon_worker_concurrency=args.daemon_worker_concurrency,
        hourly_sweep_days=args.hourly_sweep_days,
        hourly_sweep_interval_minutes=args.hourly_sweep_interval_minutes,
        backfill_state_path=args.backfill_state_path,
        backfill_checkpoint_interval=args.backfill_checkpoint_interval,
        lookback_message_limit=args.lookback_message_limit,
    )


async def main():
    """Main entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    logger.info("Starting Telegram RAG Indexer")
    logger.info(f"Mode: {'One-shot' if args.once else 'Daemon'}")

    if args.once:
        indexer = TelegramIndexer(args)
        try:
            await indexer.initialize()
            await indexer.run_once()
        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            raise
        finally:
            await indexer.cleanup()
    else:
        try:
            await run_daemon(args)
        except KeyboardInterrupt:
            logger.info("Daemon interrupted; shutting down")


def entrypoint():
    """Entry point for setuptools."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
