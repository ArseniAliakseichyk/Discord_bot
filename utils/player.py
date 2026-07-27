"""Shared wavelink player helpers.

Fetching the guild player, resolving the effective volume and connecting with the
right configuration were duplicated across ``cogs/music.py``, ``cogs/voice.py``,
``cogs/guild_settings.py`` and ``ui/controls.py``. They live here now so every call
site behaves identically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
import wavelink

if TYPE_CHECKING:
    from config import Settings
    from core.bot import MusicBot
    from core.db import GuildSettings

logger = logging.getLogger("bot.player")


def player_of(guild: discord.Guild | None) -> wavelink.Player | None:
    """Return the guild's wavelink player, or ``None`` if not connected."""
    if guild is None:
        return None
    return guild.voice_client  # type: ignore[return-value]


def resolve_volume(guild_settings: GuildSettings, bot_settings: Settings) -> int:
    """Per-guild volume if configured, otherwise the global default."""
    if guild_settings.default_volume is not None:
        return guild_settings.default_volume
    return bot_settings.default_volume


async def configure_player(player: wavelink.Player, bot: MusicBot, guild_id: int) -> None:
    """Apply autoplay mode, the inactivity timeout and the guild's default volume."""
    player.autoplay = wavelink.AutoPlayMode.partial
    player.inactive_timeout = bot.settings.inactive_timeout
    guild_settings = await bot.db.get_settings(guild_id)
    volume = resolve_volume(guild_settings, bot.settings)
    try:
        await player.set_volume(volume)
    except (wavelink.LavalinkException, wavelink.NodeException):
        logger.exception("Failed to set volume for guild %s", guild_id)


async def connect_and_configure(
    channel: discord.VoiceChannel | discord.StageChannel, bot: MusicBot
) -> wavelink.Player:
    """Connect to ``channel`` and apply the standard player configuration."""
    player: wavelink.Player = await channel.connect(cls=wavelink.Player)
    await configure_player(player, bot, channel.guild.id)
    return player
