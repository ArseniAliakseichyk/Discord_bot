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
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.bot import MusicBot

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_log_queue: "queue.SimpleQueue[str]" = queue.SimpleQueue()


class _QueueForwardHandler(logging.Handler):
    """Push formatted records into a thread-safe queue (never blocks)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_queue.put_nowait(self.format(record))
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("wavelink").setLevel(logging.INFO)


def attach_discord_handler(bot: "MusicBot", channel_id: int) -> None:
    """Forward WARNING+ logs to a Discord channel via a background drain task."""
    handler = _QueueForwardHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    bot._log_task = bot.loop.create_task(_drain_to_channel(bot, channel_id))


async def _drain_to_channel(bot: "MusicBot", channel_id: int) -> None:
    await bot.wait_until_ready()
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
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

        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1800:
                await _safe_send(channel, chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await _safe_send(channel, chunk)

        await asyncio.sleep(3)


async def _safe_send(channel: discord.abc.Messageable, text: str) -> None:
    try:
        await channel.send(f"```{text[:1990]}```", silent=True)
    except discord.HTTPException:
        pass
