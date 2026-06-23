"""Reusable checks for slash commands (app_commands).

They centralize access logic that used to be duplicated across announce/constructor/
jointo, and add private-bot authorization plus per-guild DJ/channel checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from core.bot import MusicBot


def _bot(interaction: discord.Interaction) -> "MusicBot":
    return interaction.client  # type: ignore[return-value]


class NotAuthorized(app_commands.CheckFailure):
    """Guild is not in the whitelist."""


class NotOwner(app_commands.CheckFailure):
    """Command is owner-only."""


class MissingDJRole(app_commands.CheckFailure):
    """A DJ role is required."""


class WrongChannel(app_commands.CheckFailure):
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        super().__init__()


class MissingAnnouncePerms(app_commands.CheckFailure):
    """No permission to make announcements."""


def guild_authorized() -> app_commands.check:
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise NotAuthorized("Команда доступна только на сервере.")
        if await _bot(interaction).db.is_authorized(interaction.guild.id):
            return True
        raise NotAuthorized("Этот сервер не авторизован для использования бота.")

    return app_commands.check(predicate)


def is_owner() -> app_commands.check:
    async def predicate(interaction: discord.Interaction) -> bool:
        if await _bot(interaction).is_owner(interaction.user):
            return True
        raise NotOwner("Эта команда доступна только владельцу бота.")

    return app_commands.check(predicate)


async def user_is_dj(bot: "MusicBot", member: discord.Member) -> bool:
    """Non-raising DJ check, reused by commands and UI buttons.

    True if: admin/manage_guild, OR no DJ role configured, OR member has the DJ role.
    """
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    settings = await bot.db.get_settings(member.guild.id)
    if settings.dj_role_id is None:
        return True
    return any(role.id == settings.dj_role_id for role in member.roles)


def has_dj() -> app_commands.check:
    """Allow if: admin/manage_guild, OR no DJ role configured, OR user has the DJ role."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return True
        if await user_is_dj(_bot(interaction), interaction.user):
            return True
        raise MissingDJRole("Нужна DJ-роль для управления воспроизведением.")

    return app_commands.check(predicate)


def in_command_channel() -> app_commands.check:
    """If a command channel is set, allow only there (admins bypass)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return True
        if interaction.user.guild_permissions.administrator:
            return True
        settings = await _bot(interaction).db.get_settings(interaction.guild.id)
        if settings.command_channel_id is None:
            return True
        if interaction.channel_id == settings.command_channel_id:
            return True
        raise WrongChannel(settings.command_channel_id)

    return app_commands.check(predicate)


def can_announce() -> app_commands.check:
    """Admin or one of ALLOWED_ROLES."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise MissingAnnouncePerms("Команда доступна только на сервере.")
        if interaction.user.guild_permissions.administrator:
            return True
        allowed = _bot(interaction).settings.announce_allowed_roles
        if allowed & {role.id for role in interaction.user.roles}:
            return True
        raise MissingAnnouncePerms(
            "Нет прав: нужна разрешённая роль или права администратора."
        )

    return app_commands.check(predicate)
