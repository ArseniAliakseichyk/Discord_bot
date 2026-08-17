"""Moderation: warnings, timeouts, kick/ban, purge and slowmode.

Every command that acts on a member goes through
:func:`utils.moderation.check_target` first, so role hierarchy and the bot's own
permissions are validated before any API call.

Actions are mirrored to the guild's moderation log channel when one is set with
``/mod log``.
"""

from __future__ import annotations

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.db import Warning_
from ui.v2 import notice, send_panel
from utils.checks import guild_authorized
from utils.moderation import (
    MAX_TIMEOUT,
    check_target,
    format_duration_ru,
    parse_duration,
)

logger = logging.getLogger("bot.moderation")

COLOR_WARN = 0xFEE75C
COLOR_BAD = 0xED4245
COLOR_OK = 0x57F287

#: Discord refuses bulk deletion of messages older than 14 days.
BULK_DELETE_MAX_AGE = datetime.timedelta(days=14)
PURGE_LIMIT = 100


class Moderation(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    async def _reply(
        self, interaction: discord.Interaction, text: str, *, accent: int = COLOR_OK
    ) -> None:
        await send_panel(interaction, notice(text, accent=accent), ephemeral=True)

    async def _log(self, guild: discord.Guild, text: str, *, accent: int) -> None:
        channel_id = await self.bot.db.get_mod_log_channel(guild.id)
        if channel_id is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        if not channel.permissions_for(guild.me).send_messages:
            logger.warning("No permission to write to the mod-log channel")
            return
        try:
            await channel.send(view=notice(text, accent=accent))
        except discord.HTTPException:
            logger.warning("Could not write to the mod-log channel", exc_info=True)

    async def _guard(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        *,
        bot_permission: str | None,
        action: str,
    ) -> discord.Member | None:
        """Run the shared checks; answer and return None when disallowed."""
        moderator = interaction.user
        if interaction.guild is None or not isinstance(moderator, discord.Member):
            return None
        problem = check_target(
            moderator, target, bot_permission=bot_permission, action=action
        )
        if problem is not None:
            await self._reply(interaction, problem, accent=COLOR_BAD)
            return None
        return moderator

    @staticmethod
    def _reason(moderator: discord.Member, reason: str | None) -> str:
        """Audit-log reason; Discord truncates it at 512 characters."""
        text = f"{moderator} ({moderator.id})"
        if reason:
            text += f": {reason}"
        return text[:512]

    async def _dm(self, member: discord.Member, text: str) -> bool:
        """Best-effort notice to the member. Closed DMs are not an error."""
        try:
            await member.send(view=notice(text, accent=COLOR_WARN))
        except (discord.Forbidden, discord.HTTPException):
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Warnings
    # ------------------------------------------------------------------ #
    group = app_commands.Group(
        name="mod",
        description="Модерация сервера",
        guild_only=True,
        default_permissions=discord.Permissions(moderate_members=True),
    )

    @group.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(user="Кому", reason="Причина (видна участнику)")
    @guild_authorized()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
    ) -> None:
        moderator = await self._guard(
            interaction, user, bot_permission=None, action="предупреждение"
        )
        if moderator is None or interaction.guild is None:
            return
        warning = await self.bot.db.add_warning(
            interaction.guild.id, user.id, moderator.id, reason
        )
        active = await self.bot.db.list_warnings(interaction.guild.id, user.id)
        delivered = await self._dm(
            user,
            f"⚠️ Вам выдано предупреждение на сервере **{interaction.guild.name}**.\n"
            f"**Причина:** {reason or 'не указана'}\n"
            f"Всего активных предупреждений: **{len(active)}**",
        )
        await self._reply(
            interaction,
            f"⚠️ {user.mention} предупреждён (#{warning.id}). "
            f"Активных: **{len(active)}**."
            + ("" if delivered else "\nℹ️ ЛС закрыты — уведомление не доставлено."),
            accent=COLOR_WARN,
        )
        await self._log(
            interaction.guild,
            f"⚠️ **Предупреждение #{warning.id}**\n"
            f"Участник: {user.mention} (`{user.id}`)\n"
            f"Модератор: {moderator.mention}\n"
            f"Причина: {reason or 'не указана'}\n"
            f"Активных предупреждений: {len(active)}",
            accent=COLOR_WARN,
        )

    @group.command(name="warnings", description="Показать предупреждения участника")
    @app_commands.describe(user="Чьи предупреждения показать", show_all="Включая снятые")
    @guild_authorized()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        show_all: bool = False,
    ) -> None:
        if interaction.guild is None:
            return
        items = await self.bot.db.list_warnings(
            interaction.guild.id, user.id, active_only=not show_all
        )
        if not items:
            await self._reply(
                interaction,
                f"✅ У {user.mention} нет "
                + ("предупреждений." if show_all else "активных предупреждений."),
            )
            return

        def render(w: Warning_) -> str:
            when = f"<t:{w.created_at}:d>"
            status = "" if w.active else " *(снято)*"
            return (
                f"**#{w.id}**{status} — {when} · <@{w.moderator_id}>\n"
                f"> {w.reason or 'причина не указана'}"
            )

        # Cap the list so the panel stays inside the v2 text limit.
        shown = items[:15]
        body = "\n".join(render(w) for w in shown)
        if len(items) > len(shown):
            body += f"\n\n*…и ещё {len(items) - len(shown)}.*"
        await self._reply(
            interaction,
            f"## Предупреждения {user.display_name}\nВсего: **{len(items)}**\n\n{body}",
            accent=COLOR_WARN,
        )

    @group.command(name="unwarn", description="Снять предупреждение по номеру")
    @app_commands.describe(warning_id="Номер предупреждения из /mod warnings")
    @guild_authorized()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, warning_id: int) -> None:
        if interaction.guild is None:
            return
        if await self.bot.db.deactivate_warning(interaction.guild.id, warning_id):
            await self._reply(interaction, f"✅ Предупреждение #{warning_id} снято.")
            await self._log(
                interaction.guild,
                f"♻️ Предупреждение **#{warning_id}** снято — {interaction.user.mention}",
                accent=COLOR_OK,
            )
        else:
            await self._reply(
                interaction,
                f"❌ Предупреждение #{warning_id} не найдено на этом сервере "
                "или уже снято.",
                accent=COLOR_BAD,
            )

    @group.command(name="clearwarns", description="Снять все предупреждения участника")
    @app_commands.describe(user="Кому обнулить предупреждения")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clearwarns(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if interaction.guild is None:
            return
        count = await self.bot.db.clear_warnings(interaction.guild.id, user.id)
        await self._reply(
            interaction, f"✅ Снято предупреждений у {user.mention}: **{count}**."
        )
        if count:
            await self._log(
                interaction.guild,
                f"♻️ Все предупреждения {user.mention} сняты ({count}) — "
                f"{interaction.user.mention}",
                accent=COLOR_OK,
            )

    # ------------------------------------------------------------------ #
    #  Timeout / kick / ban
    # ------------------------------------------------------------------ #
    @group.command(name="mute", description="Тайм-аут участнику (нативный мут Discord)")
    @app_commands.describe(
        user="Кому", duration="Например: 30s, 10m, 2h, 1d (максимум 28д)", reason="Причина"
    )
    @guild_authorized()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str | None = None,
    ) -> None:
        moderator = await self._guard(
            interaction, user, bot_permission="moderate_members", action="тайм-аут"
        )
        if moderator is None or interaction.guild is None:
            return
        delta = parse_duration(duration)
        if delta is None:
            await self._reply(
                interaction,
                "❌ Не понял длительность. Примеры: `30s`, `10m`, `2h`, `1d`, `1h30m`.",
                accent=COLOR_BAD,
            )
            return
        if delta > MAX_TIMEOUT:
            await self._reply(
                interaction, "❌ Максимальный тайм-аут — 28 дней.", accent=COLOR_BAD
            )
            return

        try:
            await user.timeout(delta, reason=self._reason(moderator, reason))
        except discord.Forbidden:
            await self._reply(
                interaction, "❌ Discord отклонил тайм-аут: недостаточно прав.", accent=COLOR_BAD
            )
            return
        except discord.HTTPException:
            logger.exception("Timeout failed")
            await self._reply(interaction, "⚠️ Не удалось выдать тайм-аут.", accent=COLOR_BAD)
            return

        pretty = format_duration_ru(delta)
        await self._dm(
            user,
            f"🔇 Вам выдан тайм-аут на **{pretty}** на сервере "
            f"**{interaction.guild.name}**.\n**Причина:** {reason or 'не указана'}",
        )
        await self._reply(interaction, f"🔇 {user.mention} в тайм-ауте на **{pretty}**.")
        await self._log(
            interaction.guild,
            f"🔇 **Тайм-аут**\nУчастник: {user.mention} (`{user.id}`)\n"
            f"Модератор: {moderator.mention}\nСрок: {pretty}\n"
            f"Причина: {reason or 'не указана'}",
            accent=COLOR_WARN,
        )

    @group.command(name="unmute", description="Снять тайм-аут")
    @app_commands.describe(user="С кого снять тайм-аут")
    @guild_authorized()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        moderator = await self._guard(
            interaction, user, bot_permission="moderate_members", action="снятие тайм-аута"
        )
        if moderator is None or interaction.guild is None:
            return
        if user.timed_out_until is None:
            await self._reply(interaction, "ℹ️ У участника нет активного тайм-аута.")
            return
        try:
            await user.timeout(None, reason=self._reason(moderator, "снятие тайм-аута"))
        except discord.HTTPException:
            await self._reply(interaction, "⚠️ Не удалось снять тайм-аут.", accent=COLOR_BAD)
            return
        await self._reply(interaction, f"🔊 Тайм-аут с {user.mention} снят.")
        await self._log(
            interaction.guild,
            f"🔊 Тайм-аут снят с {user.mention} — {moderator.mention}",
            accent=COLOR_OK,
        )

    @group.command(name="kick", description="Выгнать участника с сервера")
    @app_commands.describe(user="Кого", reason="Причина")
    @guild_authorized()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
    ) -> None:
        moderator = await self._guard(
            interaction, user, bot_permission="kick_members", action="кик"
        )
        if moderator is None or interaction.guild is None:
            return
        # Send the DM first: after the kick the mutual guild is gone and Discord
        # will not open a DM channel any more.
        await self._dm(
            user,
            f"👢 Вас выгнали с сервера **{interaction.guild.name}**.\n"
            f"**Причина:** {reason or 'не указана'}",
        )
        try:
            await user.kick(reason=self._reason(moderator, reason))
        except discord.Forbidden:
            await self._reply(interaction, "❌ Discord отклонил кик.", accent=COLOR_BAD)
            return
        except discord.HTTPException:
            logger.exception("Kick failed")
            await self._reply(interaction, "⚠️ Не удалось выгнать участника.", accent=COLOR_BAD)
            return
        await self._reply(interaction, f"👢 {user.mention} выгнан.")
        await self._log(
            interaction.guild,
            f"👢 **Кик**\nУчастник: {user} (`{user.id}`)\n"
            f"Модератор: {moderator.mention}\nПричина: {reason or 'не указана'}",
            accent=COLOR_BAD,
        )

    @group.command(name="ban", description="Забанить участника")
    @app_commands.describe(
        user="Кого",
        reason="Причина",
        delete_days="Удалить сообщения за N последних дней (0–7)",
    )
    @guild_authorized()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        moderator = await self._guard(
            interaction, user, bot_permission="ban_members", action="бан"
        )
        if moderator is None or interaction.guild is None:
            return
        await self._dm(
            user,
            f"🔨 Вы забанены на сервере **{interaction.guild.name}**.\n"
            f"**Причина:** {reason or 'не указана'}",
        )
        try:
            await interaction.guild.ban(
                user,
                reason=self._reason(moderator, reason),
                delete_message_days=delete_days,
            )
        except discord.Forbidden:
            await self._reply(interaction, "❌ Discord отклонил бан.", accent=COLOR_BAD)
            return
        except discord.HTTPException:
            logger.exception("Ban failed")
            await self._reply(interaction, "⚠️ Не удалось забанить.", accent=COLOR_BAD)
            return
        await self._reply(interaction, f"🔨 {user.mention} забанен.")
        await self._log(
            interaction.guild,
            f"🔨 **Бан**\nУчастник: {user} (`{user.id}`)\n"
            f"Модератор: {moderator.mention}\nПричина: {reason or 'не указана'}",
            accent=COLOR_BAD,
        )

    @group.command(name="unban", description="Разбанить по ID пользователя")
    @app_commands.describe(user_id="ID пользователя", reason="Причина")
    @guild_authorized()
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not user_id.isdigit():
            await self._reply(interaction, "❌ ID должен состоять только из цифр.", accent=COLOR_BAD)
            return
        if not guild.me.guild_permissions.ban_members:
            await self._reply(interaction, "❌ У бота нет права «Банить участников».", accent=COLOR_BAD)
            return
        try:
            await guild.unban(
                discord.Object(id=int(user_id)),
                reason=self._reason(interaction.user, reason),
            )
        except discord.NotFound:
            await self._reply(interaction, "❌ Этот пользователь не забанен.", accent=COLOR_BAD)
            return
        except discord.HTTPException:
            logger.exception("Unban failed")
            await self._reply(interaction, "⚠️ Не удалось разбанить.", accent=COLOR_BAD)
            return
        await self._reply(interaction, f"✅ Пользователь `{user_id}` разбанен.")
        await self._log(
            guild,
            f"♻️ Разбан `{user_id}` — {interaction.user.mention}",
            accent=COLOR_OK,
        )

    # ------------------------------------------------------------------ #
    #  Channel tools
    # ------------------------------------------------------------------ #
    @group.command(name="purge", description="Удалить последние сообщения в канале")
    @app_commands.describe(count="Сколько сообщений (1–100)", user="Только этого автора")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, PURGE_LIMIT],
        user: discord.Member | None = None,
    ) -> None:
        channel = interaction.channel
        guild = interaction.guild
        if guild is None or not isinstance(channel, discord.TextChannel):
            await self._reply(
                interaction, "❌ Команда работает только в текстовом канале.", accent=COLOR_BAD
            )
            return
        if not channel.permissions_for(guild.me).manage_messages:
            await self._reply(
                interaction, "❌ У бота нет права «Управление сообщениями».", accent=COLOR_BAD
            )
            return

        await interaction.response.defer(ephemeral=True)
        cutoff = discord.utils.utcnow() - BULK_DELETE_MAX_AGE

        def matches(message: discord.Message) -> bool:
            # Bulk delete silently ignores messages older than 14 days; filter
            # them out so the reported count is the real one.
            if message.created_at <= cutoff:
                return False
            return user is None or message.author.id == user.id

        try:
            deleted = await channel.purge(limit=count, check=matches, reason=f"/mod purge — {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                view=notice("❌ Недостаточно прав для удаления.", accent=COLOR_BAD),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Purge failed")
            await interaction.followup.send(
                view=notice("⚠️ Не удалось удалить сообщения.", accent=COLOR_BAD),
                ephemeral=True,
            )
            return

        suffix = f" от {user.mention}" if user else ""
        await interaction.followup.send(
            view=notice(f"🧹 Удалено сообщений{suffix}: **{len(deleted)}**."),
            ephemeral=True,
        )
        await self._log(
            guild,
            f"🧹 **Очистка**\nКанал: {channel.mention}\n"
            f"Удалено: {len(deleted)}\nМодератор: {interaction.user.mention}",
            accent=COLOR_WARN,
        )

    @group.command(name="slowmode", description="Медленный режим в канале")
    @app_commands.describe(seconds="Задержка в секундах, 0 — выключить (максимум 21600)")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
    ) -> None:
        channel = interaction.channel
        guild = interaction.guild
        if guild is None or not isinstance(channel, discord.TextChannel):
            await self._reply(
                interaction, "❌ Команда работает только в текстовом канале.", accent=COLOR_BAD
            )
            return
        if not channel.permissions_for(guild.me).manage_channels:
            await self._reply(
                interaction, "❌ У бота нет права «Управление каналами».", accent=COLOR_BAD
            )
            return
        try:
            await channel.edit(slowmode_delay=seconds, reason=f"/mod slowmode — {interaction.user}")
        except discord.HTTPException:
            await self._reply(interaction, "⚠️ Не удалось изменить режим.", accent=COLOR_BAD)
            return
        if seconds:
            await self._reply(interaction, f"🐌 Медленный режим: **{seconds} с**.")
        else:
            await self._reply(interaction, "✅ Медленный режим выключен.")

    # ------------------------------------------------------------------ #
    #  Configuration
    # ------------------------------------------------------------------ #
    @group.command(name="log", description="Канал для журнала модерации")
    @app_commands.describe(channel="Канал; пусто — выключить журнал")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_log(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        await self.bot.db.set_mod_log_channel(
            interaction.guild.id, channel.id if channel else None
        )
        await self._reply(
            interaction,
            f"✅ Журнал модерации: {channel.mention if channel else 'выключен'}",
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Moderation(bot))
