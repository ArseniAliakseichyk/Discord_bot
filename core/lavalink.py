"""Lavalink connection via wavelink."""

from __future__ import annotations

import asyncio
import logging

import discord
import wavelink

logger = logging.getLogger("bot.lavalink")

#: Number of tracks wavelink keeps in its per-node cache.
NODE_CACHE_CAPACITY = 100


async def connect_nodes(
    client: discord.Client,
    uri: str,
    password: str,
    *,
    retries: int = 10,
    delay: float = 5.0,
    cache_capacity: int = NODE_CACHE_CAPACITY,
) -> None:
    """Connect the wavelink pool to a Lavalink node, retrying while it boots.

    Lavalink (a separate container) may start a few seconds after the bot, so the
    initial connection is retried. Once a node is registered, wavelink reconnects
    on its own — but if every attempt here fails, no node is ever registered and
    music stays unavailable until the process restarts. Callers must treat an
    exception from this function as fatal for playback.
    """
    if retries <= 0:
        raise ValueError("retries must be at least 1")

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            node = wavelink.Node(uri=uri, password=password)
            await wavelink.Pool.connect(
                nodes=[node], client=client, cache_capacity=cache_capacity
            )
            logger.info("Lavalink node registered: %s", uri)
            return
        except wavelink.AuthorizationFailedException:
            # A wrong password will never succeed; retrying just wastes startup time.
            logger.error("Lavalink rejected the password for %s", uri)
            raise
        except (TimeoutError, wavelink.NodeException, OSError) as error:
            last_error = error
            logger.warning(
                "Lavalink connect attempt %d/%d failed: %s", attempt, retries, error
            )
            if attempt < retries:  # no point sleeping after the final attempt
                await asyncio.sleep(delay)

    # retries >= 1, so the loop ran and either returned or recorded an error.
    raise last_error if last_error is not None else RuntimeError(
        f"Could not connect to Lavalink at {uri}"
    )
