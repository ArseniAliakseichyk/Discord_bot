"""Global events: guild authorization, node readiness, activity logging."""

from __future__ import annotations

import logging

import discord
import wavelink
from discord.ext import commands

from core.bot import MusicBot
from utils.formatting import format_user

logger = logging.getLogger("bot.events")


class Events(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        # on_ready fires again after every gateway reconnect; audit only once so
        # the "unauthorized" notice is not re-posted on every reconnect.
        self._audited = False

    def is_excluded(self, user: discord.abc.User) -> bool:
        return user.id in self.bot.settings.excluded_user_ids

    # ------------------------------------------------------------------ #
    #  Private-bot authorization
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.info("✅ Bot %s is ready (%d guilds)", self.bot.user, len(self.bot.guilds))
        if self._audited:
            return
        self._audited = True
        await self._audit_guilds()

    async def _audit_guilds(self) -> None:
        authorized = await self.bot.db.authorized_guilds()
        for guild in list(self.bot.guilds):
            if guild.id not in authorized:
                logger.warning(
                    "⛔ Unauthorized guild on startup: %s (%s) — leaving",
                    guild.name,
                    guild.id,
                )
                await self._notify_and_leave(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if await self.bot.db.is_authorized(guild.id):
            logger.info("➕ Joined authorized guild %s (%s)", guild.name, guild.id)
        else:
            logger.warning(
                "⛔ Joined unauthorized guild %s (%s) — leaving", guild.name, guild.id
            )
            await self._notify_and_leave(guild)

    async def _notify_and_leave(self, guild: discord.Guild) -> None:
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            channel = next(
                (
                    c
                    for c in guild.text_channels
                    if c.permissions_for(guild.me).send_messages
                ),
                None,
            )
        if channel is not None:
            try:
                await channel.send(
                    "🔒 Это приватный бот. Сервер не авторизован — выхожу.\n"
                    "Обратитесь к владельцу бота, чтобы он выполнил `/authorize`."
                )
            except discord.HTTPException:
                pass
        try:
            await guild.leave()
        except discord.HTTPException:
            logger.exception("Failed to leave guild %s (%s)", guild.name, guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        logger.info("➖ Removed from guild: %s (%s)", guild.name, guild.id)

    # ------------------------------------------------------------------ #
    #  Lavalink
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        # cogs.music also listens for this event, to restore saved sessions.
        logger.info(
            "🟢 Lavalink node ready: %s (resumed=%s)",
            payload.node.identifier,
            payload.resumed,
        )

    # ------------------------------------------------------------------ #
    #  Activity logging (to file/console; Discord channel gets WARNING+ only)
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.is_excluded(message.author):
            return
        where = f"#{message.channel} @ {message.guild}"
        # Message bodies are personal data and go to DEBUG only; INFO keeps the
        # metadata so bot.log stays useful without transcribing every chat.
        logger.info("📩 %s in %s (%d chars)", format_user(message.author), where, len(message.content))
        logger.debug("📩 %s in %s: %s", format_user(message.author), where, message.content)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if (
            before.author.bot
            or self.is_excluded(before.author)
            or before.content == after.content
        ):
            return
        logger.info("✏️ %s edited a message in #%s", format_user(before.author), before.channel)
        logger.debug(
            "✏️ %s edited in #%s:\n  before: %s\n  after:  %s",
            format_user(before.author),
            before.channel,
            before.content,
            after.content,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or self.is_excluded(message.author):
            return
        logger.info(
            "🗑️ Deleted message by %s in #%s", format_user(message.author), message.channel
        )
        logger.debug(
            "🗑️ Deleted message by %s in #%s: %s",
            format_user(message.author),
            message.channel,
            message.content,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self.is_excluded(member):
            logger.info("👤 %s joined %s", format_user(member), member.guild.name)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not self.is_excluded(member):
            logger.info("🚪 %s left %s", format_user(member), member.guild.name)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or self.is_excluded(member) or before.channel == after.channel:
            return
        if after.channel is not None:
            logger.info("🔊 %s joined VC: %s", format_user(member), after.channel.name)
        elif before.channel is not None:
            logger.info("🔇 %s left VC: %s", format_user(member), before.channel.name)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Events(bot))
