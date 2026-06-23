"""Lavalink connection via wavelink."""

from __future__ import annotations

import asyncio
import logging

import discord
import wavelink

logger = logging.getLogger("bot.lavalink")


async def connect_nodes(
    client: discord.Client,
    uri: str,
    password: str,
    *,
    retries: int = 10,
    delay: float = 5.0,
) -> None:
    """Connect the wavelink pool to a Lavalink node, retrying while it boots.

    Lavalink (a separate container) may start a few seconds after the bot, so we
    retry the initial connection. After it succeeds, wavelink reconnects on its own.
    """
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            node = wavelink.Node(uri=uri, password=password)
            await wavelink.Pool.connect(nodes=[node], client=client, cache_capacity=100)
            logger.info("Lavalink node registered: %s", uri)
            return
        except Exception as error:
            last_error = error
            logger.warning(
                "Lavalink connect attempt %d/%d failed: %s", attempt, retries, error
            )
            await asyncio.sleep(delay)
    if last_error is not None:
        raise last_error
