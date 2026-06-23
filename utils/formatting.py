"""Formatting helpers (single place — removes duplication)."""

from __future__ import annotations

import discord


def format_duration(seconds: float | int) -> str:
    """Seconds -> ``MM:SS`` or ``H:MM:SS``."""
    seconds = int(seconds)
    if seconds <= 0:
        return "00:00"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_user(user: discord.User | discord.Member) -> str:
    """``Name (@username)`` without the deprecated discriminator."""
    return f"{user.display_name} (@{user.name})"
