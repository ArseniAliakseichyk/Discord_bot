"""Allowed-mentions helpers.

The bot itself normally holds "Mention @everyone, @here and All Roles", so any
`AllowedMentions(everyone=True, roles=True)` on a send lets whoever triggered it
ping the whole server — regardless of their own permissions. ``can_announce()``
only gates *who may invoke* the command, so these helpers re-apply the invoker's
real permissions to the outgoing message.
"""

from __future__ import annotations

import discord

#: Discord rejects an allowed_mentions payload with more than 100 role ids.
MAX_ALLOWED_ROLES = 100


def _can_mention_everyone(
    user: discord.Member | discord.User, channel: discord.abc.GuildChannel
) -> bool:
    if not isinstance(user, discord.Member):
        return False
    return channel.permissions_for(user).mention_everyone


def mentions_for_role(
    user: discord.Member | discord.User,
    channel: discord.abc.GuildChannel,
    role: discord.Role | None,
) -> discord.AllowedMentions:
    """Allowed mentions for an announcement that pings at most one known role.

    The role is pinged only if the invoker could have pinged it themselves: either
    the role is mentionable, or they hold "Mention @everyone, @here and All Roles".
    """
    privileged = _can_mention_everyone(user, channel)
    if role is None:
        allowed_roles: list[discord.Role] | bool = False
    elif privileged or role.mentionable:
        allowed_roles = [role]
    else:
        allowed_roles = False
    return discord.AllowedMentions(
        everyone=privileged, roles=allowed_roles, users=True
    )


def mentions_for_free_text(
    user: discord.Member | discord.User,
    channel: discord.abc.GuildChannel,
    guild: discord.Guild,
) -> discord.AllowedMentions:
    """Allowed mentions for user-authored body text with arbitrary mentions in it.

    Without ``mention_everyone`` the invoker gets exactly what they could have
    typed themselves: no ``@everyone``/``@here``, and only roles that are already
    mentionable by anyone.
    """
    if _can_mention_everyone(user, channel):
        return discord.AllowedMentions(everyone=True, roles=True, users=True)
    mentionable = [role for role in guild.roles if role.mentionable]
    return discord.AllowedMentions(
        everyone=False, roles=mentionable[:MAX_ALLOWED_ROLES], users=True
    )
