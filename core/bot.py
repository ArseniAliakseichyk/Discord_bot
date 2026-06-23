"""Bot subclass and its lifecycle."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from core.db import Database
from core.lavalink import connect_nodes
from utils import checks
from utils.logging import attach_discord_handler

logger = logging.getLogger("bot")

INITIAL_EXTENSIONS: tuple[str, ...] = (
    "cogs.events",
    "cogs.owner",
    "cogs.music",
    "cogs.voice",
    "cogs.guild_settings",
    "cogs.admin",
    "cogs.builder",
    "cogs.help",
)


class MusicBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=settings.intents,
            help_command=None,
            # Music embeds etc. must not ping @everyone/roles. Announcements
            # opt into mentions explicitly, on the specific send.
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True
            ),
        )
        self.settings = settings
        self.db = Database(settings.database_path)
        if settings.owner_ids:
            self.owner_ids = set(settings.owner_ids)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        await self.db.connect()
        logger.info("Database connected: %s", self.settings.database_path)

        if self.settings.log_channel_id:
            attach_discord_handler(self, self.settings.log_channel_id)

        try:
            await connect_nodes(
                self, self.settings.lavalink_uri, self.settings.lavalink_password
            )
        except Exception:
            logger.exception("Failed to connect to Lavalink (wavelink will retry)")

        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info("Loaded extension %s", ext)
            except Exception:
                logger.exception("Failed to load extension %s", ext)

        synced = await self.tree.sync()
        logger.info("Synced %d application commands", len(synced))

    async def is_owner(self, user: discord.abc.User) -> bool:  # type: ignore[override]
        if self.settings.owner_ids and user.id in self.settings.owner_ids:
            return True
        return await super().is_owner(user)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"⏳ Помедленнее: попробуйте через {error.retry_after:.1f} с."
        elif isinstance(error, checks.WrongChannel):
            message = f"❌ Используйте команды в <#{error.channel_id}>."
        elif isinstance(
            error,
            (
                checks.NotAuthorized,
                checks.NotOwner,
                checks.MissingDJRole,
                checks.MissingAnnouncePerms,
            ),
        ):
            message = f"❌ {error}"
        elif isinstance(error, app_commands.MissingPermissions):
            message = "❌ Недостаточно прав."
        elif isinstance(error, app_commands.CheckFailure):
            message = "❌ Условие выполнения команды не соблюдено."
        else:
            logger.exception("Unhandled app command error", exc_info=error)
            message = "⚠️ Произошла внутренняя ошибка."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await self.db.close()
        await super().close()
