"""Shared guards and parsing for moderation commands.

Every moderation command funnels through :func:`check_target` before touching
Discord. Without it the commands fail with a bare ``Forbidden`` traceback when
the target outranks the bot, and — worse — a moderator with the right Discord
permission but a low role could try to act on an administrator.

The rules mirror Discord's own: you cannot moderate yourself, the bot, the
guild owner, or anyone whose top role is at or above your own; and the bot
cannot moderate anyone at or above *its* top role.
"""

from __future__ import annotations

import re
from datetime import timedelta

import discord

#: Discord's hard cap on a communication timeout.
MAX_TIMEOUT = timedelta(days=28)

_DURATION_RE = re.compile(r"(?P<value>\d+)\s*(?P<unit>[smhdw])", re.IGNORECASE)
_UNITS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


def parse_duration(text: str) -> timedelta | None:
    """Parse ``"10m"``, ``"1h30m"``, ``"2d"``. Returns None if unparseable.

    A bare number is read as minutes, which is what people usually mean when
    they type ``/mute @user 10``.
    """
    text = text.strip().lower()
    if not text:
        return None
    if text.isdigit():
        return timedelta(minutes=int(text))

    total = timedelta()
    matched = 0
    for match in _DURATION_RE.finditer(text):
        total += _UNITS[match.group("unit").lower()] * int(match.group("value"))
        matched += len(match.group(0))
    # Reject partially-parsed junk like "10x" rather than silently using "10".
    if matched != len(text.replace(" ", "")):
        return None
    return total or None


def format_duration_ru(delta: timedelta) -> str:
    """Human-readable duration for user-facing messages."""
    seconds = int(delta.total_seconds())
    parts: list[str] = []
    for count, label in (
        (seconds // 86400, "д"),
        (seconds % 86400 // 3600, "ч"),
        (seconds % 3600 // 60, "мин"),
        (seconds % 60, "с"),
    ):
        if count:
            parts.append(f"{count}{label}")
    return " ".join(parts) or "0с"


def check_target(
    moderator: discord.Member,
    target: discord.Member,
    *,
    bot_permission: str | None = None,
    action: str = "это действие",
) -> str | None:
    """Validate a moderation action. Returns an error message, or None if OK.

    ``bot_permission`` is the attribute name on :class:`discord.Permissions`
    the bot needs (e.g. ``"ban_members"``).
    """
    guild = target.guild
    me = guild.me

    if target.id == moderator.id:
        return f"❌ Нельзя применить {action} к себе."
    if target.id == me.id:
        return f"❌ Нельзя применить {action} к боту."
    if target.id == guild.owner_id:
        return f"❌ Нельзя применить {action} к владельцу сервера."

    if bot_permission is not None and not getattr(
        me.guild_permissions, bot_permission, False
    ):
        return f"❌ У бота нет права «{PERMISSION_NAMES.get(bot_permission, bot_permission)}»."

    # The guild owner outranks everyone, including their own top role position.
    if moderator.id != guild.owner_id and moderator.top_role <= target.top_role:
        return (
            f"❌ У {target.mention} роль не ниже вашей — "
            f"применить {action} нельзя."
        )
    if me.top_role <= target.top_role:
        return (
            f"❌ Роль {target.mention} выше роли бота. "
            "Поднимите роль бота в настройках сервера."
        )
    return None


#: Russian names for the permissions the moderation commands need, so the error
#: message matches what the user sees in Discord's own settings UI.
PERMISSION_NAMES = {
    "ban_members": "Банить участников",
    "kick_members": "Выгонять участников",
    "moderate_members": "Тайм-аут участников",
    "manage_messages": "Управление сообщениями",
    "manage_channels": "Управление каналами",
    "manage_roles": "Управление ролями",
}
