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


def format_ms(milliseconds: float | int) -> str:
    """Milliseconds -> ``MM:SS`` or ``H:MM:SS`` (wavelink reports track lengths in ms)."""
    return format_duration(milliseconds / 1000)


def format_user(user: discord.abc.User) -> str:
    """``Name (@username)`` without the deprecated discriminator.

    Takes the abstract user type: reaction events hand over a ``User`` that is
    not necessarily a full ``Member``.
    """
    return f"{user.display_name} (@{user.name})"


def parse_position(text: str) -> int | None:
    """Parse a seek position into milliseconds. None if unparseable.

    Accepts ``90`` (seconds), ``1:30`` (m:s) and ``1:02:03`` (h:m:s). Rejects
    negatives and out-of-range parts such as ``1:75`` so ``/seek 1:75`` reports
    a typo instead of silently jumping somewhere unexpected.
    """
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3 or not all(p.strip().isdigit() for p in parts):
        return None
    values = [int(p) for p in parts]
    if len(values) > 1 and any(v > 59 for v in values[1:]):
        return None
    seconds = 0
    for value in values:
        seconds = seconds * 60 + value
    return seconds * 1000
