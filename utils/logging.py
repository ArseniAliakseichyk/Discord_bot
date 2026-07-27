"""Logging setup.

Console + file always. Optionally a Discord-channel handler for WARNING+ that is
non-blocking: ``emit`` only drops the formatted line into a thread-safe queue, and
a background task drains it and posts batched messages from the bot's event loop.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.bot import MusicBot

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

LOG_FILE = "bot.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3

#: Batch size for the Discord relay; Discord's hard limit is 2000 per message and
#: the code fence plus newlines need headroom.
_CHUNK_LIMIT = 1800
_DRAIN_INTERVAL = 3.0

_log_queue: queue.SimpleQueue[str] = queue.SimpleQueue()


class _QueueForwardHandler(logging.Handler):
    """Push formatted records into a thread-safe queue (never blocks)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_queue.put_nowait(self.format(record))
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            pass


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging. Idempotent — calling it twice does not duplicate output."""
    root = logging.getLogger()
    root.setLevel(level)

    # Without this guard a second call adds another console + file handler and
    # every line is emitted twice.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("wavelink").setLevel(logging.INFO)


def attach_discord_handler(bot: MusicBot, channel_id: int) -> asyncio.Task[None]:
    """Forward WARNING+ logs to a Discord channel via a background drain task.

    Returns the task so the caller owns its lifetime and can cancel it on shutdown.
    """
    handler = _QueueForwardHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    return bot.loop.create_task(_drain_to_channel(bot, channel_id, handler))


def _split_lines(lines: list[str], limit: int = _CHUNK_LIMIT) -> list[str]:
    """Group log lines into chunks no longer than ``limit`` characters."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        # A single oversized line cannot be batched; emit it on its own, split up.
        if len(line) + 1 > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit])
            continue
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    return chunks


async def _drain_to_channel(
    bot: MusicBot, channel_id: int, handler: logging.Handler
) -> None:
    try:
        await bot.wait_until_ready()
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger = logging.getLogger("bot.logging")
                logger.warning("Log channel %s is unavailable; relay disabled", channel_id)
                return
        if not isinstance(channel, discord.abc.Messageable):
            return

        while not bot.is_closed():
            lines: list[str] = []
            try:
                while True:
                    lines.append(_log_queue.get_nowait())
            except queue.Empty:
                pass

            for chunk in _split_lines(lines):
                await _safe_send(channel, chunk)

            await asyncio.sleep(_DRAIN_INTERVAL)
    except asyncio.CancelledError:
        raise
    finally:
        # Whatever happens, stop feeding a queue nobody drains any more.
        logging.getLogger().removeHandler(handler)


async def _safe_send(channel: discord.abc.Messageable, text: str) -> None:
    if not text.strip():
        return
    try:
        await channel.send(f"```{text[:_CHUNK_LIMIT]}```", silent=True)
    except discord.HTTPException:
        pass
