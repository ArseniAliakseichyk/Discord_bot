"""Rules panel, button verification and the support-ticket workflow.

Configuration lives in the ``ticket_config`` table (one row per guild) and open
tickets in ``tickets``, so the same bot serves several guilds and nothing
depends on a global ``.env`` id or an on-disk counter file.

Command surface is ``/ticket …`` with a ``config`` subgroup rather than
``/settings tickets …``: an ``app_commands.Group`` belongs to the cog that
declares it, so keeping the ticket configuration next to the ticket code avoids
attaching commands to another cog's group object.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.constants import EMBED_COLOR
from core.db import Ticket
from ui.tickets import (
    CATEGORY_LABELS,
    DEFAULT_RULES,
    RulesPanel,
    TicketControls,
    TicketModal,
    is_support,
)
from ui.v2 import notice, send_panel
from utils.checks import guild_authorized

logger = logging.getLogger("bot.tickets")

#: Cap on simultaneously open tickets per member — stops one user filling the
#: category with channels by spamming the button.
MAX_OPEN_TICKETS = 3

#: Discord's own cap on channels in a category.
CATEGORY_CHANNEL_LIMIT = 50


def _channel_name(number: int, member: discord.abc.User, subject: str) -> str:
    """Build a ticket channel name that Discord will accept.

    Discord lowercases names and strips most punctuation anyway; doing it here
    keeps the stored name and the real one identical.
    """

    def clean(text: str, limit: int) -> str:
        kept = "".join(c if c.isalnum() else "-" for c in text.lower())
        return "-".join(part for part in kept.split("-") if part)[:limit].strip("-")

    parts = [f"ticket-{number:04d}", clean(member.display_name, 12), clean(subject, 16)]
    return "-".join(p for p in parts if p)[:100]


class Tickets(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    async def _reply(
        self, interaction: discord.Interaction, text: str, *, accent: int = EMBED_COLOR
    ) -> None:
        """Send a short ephemeral v2 panel (a v2 message has no `content`)."""
        await send_panel(interaction, notice(text, accent=accent), ephemeral=True)

    async def _log(self, guild: discord.Guild, text: str) -> None:
        """Mirror a ticket event to the configured log channel, if any."""
        config = await self.bot.db.get_ticket_config(guild.id)
        if config.log_channel_id is None:
            return
        channel = guild.get_channel(config.log_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        if isinstance(channel, discord.TextChannel) and not channel.permissions_for(
            guild.me
        ).send_messages:
            return
        try:
            await channel.send(view=notice(text))
        except discord.HTTPException:
            logger.warning("Could not write to the ticket log channel", exc_info=True)

    async def _require_ticket(
        self, interaction: discord.Interaction
    ) -> Ticket | None:
        """Return the ticket for the current channel, or answer and return None."""
        if interaction.channel_id is None:
            return None
        ticket = await self.bot.db.get_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            await self._reply(interaction, "❌ Эта команда работает только в канале тикета.")
            return None
        return ticket

    # ------------------------------------------------------------------ #
    #  Panel callbacks (ui.tickets.TicketHost)
    # ------------------------------------------------------------------ #
    async def verify_member(self, interaction: discord.Interaction) -> None:
        guild, member = interaction.guild, interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        if config.verify_role_id is None:
            await self._reply(interaction, "❌ Роль верификации не настроена на сервере.")
            return
        role = guild.get_role(config.verify_role_id)
        if role is None:
            logger.warning(
                "Verify role %s is gone on guild %s", config.verify_role_id, guild.id
            )
            await self._reply(interaction, "❌ Роль верификации не найдена — сообщите администрации.")
            return
        if role in member.roles:
            await self._reply(interaction, "ℹ️ Вы уже прошли верификацию.")
            return
        # Discord refuses role grants at or above the bot's own top role; check
        # first so the user gets a clear reason instead of a generic failure.
        if role >= guild.me.top_role:
            logger.warning("Verify role %s is above the bot's top role", role.id)
            await self._reply(
                interaction,
                "❌ У бота недостаточно прав, чтобы выдать эту роль "
                "(она выше роли бота). Сообщите администрации.",
            )
            return
        try:
            await member.add_roles(role, reason="Верификация по кнопке с правилами")
        except discord.Forbidden:
            await self._reply(interaction, "❌ У бота нет права «Управление ролями».")
            return
        except discord.HTTPException:
            logger.exception("Failed to grant the verify role")
            await self._reply(interaction, "⚠️ Не удалось выдать роль. Попробуйте позже.")
            return

        logger.info(
            "✅ Verified %s (%s) on %s", member.display_name, member.id, guild.name
        )
        await self._reply(
            interaction,
            "✅ Верификация пройдена!\n\n"
            "ℹ️ Если история каналов отображается неправильно — перезапустите Discord.",
            accent=0x57F287,
        )

    async def prompt_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        if not config.tickets_ready:
            await self._reply(
                interaction,
                "❌ Система тикетов не настроена: нужны категория и роль поддержки.\n"
                "Администратору: `/ticket config category` и `/ticket config support-role`.",
            )
            return
        open_count = await self.bot.db.open_tickets_for(guild.id, interaction.user.id)
        if open_count >= MAX_OPEN_TICKETS:
            await self._reply(
                interaction,
                f"❌ У вас уже {open_count} открытых обращений. "
                "Дождитесь ответа по ним, прежде чем создавать новое.",
            )
            return
        await interaction.response.send_modal(TicketModal(self))

    async def show_help(self, interaction: discord.Interaction) -> None:
        help_cog = self.bot.get_cog("Help")
        show = getattr(help_cog, "send_help_panel", None)
        if show is None:
            await self._reply(interaction, "ℹ️ Справка временно недоступна — используйте `/help`.")
            return
        await show(interaction)

    async def open_ticket(
        self,
        interaction: discord.Interaction,
        *,
        category: str,
        subject: str,
        body: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, member = interaction.guild, interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        config = await self.bot.db.get_ticket_config(guild.id)
        if not config.tickets_ready:
            await interaction.followup.send(
                view=notice("❌ Система тикетов не настроена."), ephemeral=True
            )
            return

        parent = guild.get_channel(config.category_id or 0)
        if not isinstance(parent, discord.CategoryChannel):
            await interaction.followup.send(
                view=notice("❌ Категория для тикетов не найдена — сообщите администрации."),
                ephemeral=True,
            )
            return
        if len(parent.channels) >= CATEGORY_CHANNEL_LIMIT:
            await interaction.followup.send(
                view=notice("❌ В категории тикетов не осталось места. Сообщите администрации."),
                ephemeral=True,
            )
            return
        if not guild.me.guild_permissions.manage_channels:
            await interaction.followup.send(
                view=notice("❌ У бота нет права «Управление каналами»."), ephemeral=True
            )
            return

        support_role = guild.get_role(config.support_role_id or 0)
        overwrites: dict[
            discord.Role | discord.Member | discord.Object,
            discord.PermissionOverwrite,
        ] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
            # The author is deliberately hidden until support claims the ticket;
            # this mirrors the original workflow and keeps unread tickets out of
            # the reporter's sidebar until somebody is actually handling it.
            member: discord.PermissionOverwrite(view_channel=False),
        }
        if support_role is not None:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, embed_links=True
            )

        try:
            channel = await guild.create_text_channel(
                name=_channel_name(1, member, subject),  # renamed below with the id
                category=parent,
                overwrites=overwrites,
                reason=f"Тикет от {member} ({member.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                view=notice("❌ У бота нет прав создать канал в этой категории."),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Failed to create a ticket channel")
            await interaction.followup.send(
                view=notice("⚠️ Не удалось создать канал тикета."), ephemeral=True
            )
            return

        try:
            ticket = await self.bot.db.create_ticket(
                guild_id=guild.id,
                channel_id=channel.id,
                owner_id=member.id,
                category=category,
                subject=subject,
            )
        except Exception:
            # The channel exists but is not tracked — remove it rather than
            # leave an orphan nobody can claim or close.
            logger.exception("Failed to record the ticket; removing the channel")
            try:
                await channel.delete(reason="Тикет не удалось записать в базу")
            except discord.HTTPException:
                logger.warning("Could not remove the orphaned ticket channel")
            await interaction.followup.send(
                view=notice("⚠️ Не удалось зарегистрировать тикет."), ephemeral=True
            )
            return

        try:
            await channel.edit(name=_channel_name(ticket.number, member, subject))
        except discord.HTTPException:
            logger.debug("Could not rename the ticket channel", exc_info=True)

        mention = support_role.mention if support_role else "Администрация"
        await channel.send(
            content=f"{mention}, поступил новый тикет.",
            allowed_mentions=discord.AllowedMentions(roles=[support_role])
            if support_role
            else discord.AllowedMentions.none(),
        )
        await channel.send(
            view=TicketControls(
                self,
                number=ticket.number,
                owner=member,
                category=category,
                subject=subject,
                body=body,
            )
        )

        await interaction.followup.send(
            view=notice(
                f"✅ Обращение **#{ticket.number:04d}** создано.\n"
                "Ожидайте — администрация возьмёт его в работу.\n\n"
                "ℹ️ Канал станет вам виден, когда сотрудник поддержки его откроет.",
                accent=0x57F287,
            ),
            ephemeral=True,
        )
        await self._log(
            guild,
            f"📨 Тикет **#{ticket.number:04d}** ({CATEGORY_LABELS.get(category, category)}) "
            f"от {member.mention} — {channel.mention}",
        )

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        guild, member = interaction.guild, interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        ticket = await self._require_ticket(interaction)
        if ticket is None:
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        if not is_support(member, config.support_role_id):
            await self._reply(interaction, "❌ Брать тикеты в работу может только поддержка.")
            return
        if not await self.bot.db.claim_ticket(ticket.channel_id, member.id):
            await self._reply(interaction, "ℹ️ Этот тикет уже взят в работу или закрыт.")
            return

        await interaction.response.defer()
        owner = guild.get_member(ticket.owner_id)
        channel = interaction.channel
        if owner is not None and isinstance(channel, discord.TextChannel):
            try:
                await channel.set_permissions(
                    owner,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    reason="Тикет взят в работу",
                )
            except discord.HTTPException:
                logger.warning("Could not grant the ticket author access", exc_info=True)
            try:
                await channel.edit(name=f"claimed-{channel.name}"[:100])
            except discord.HTTPException:
                logger.debug("Could not rename the claimed ticket", exc_info=True)

        await interaction.edit_original_response(
            view=TicketControls(
                self,
                number=ticket.number,
                owner=owner,
                category=ticket.category,
                subject=ticket.subject or "",
                claimed_by=member,
            )
        )
        if isinstance(channel, discord.abc.Messageable):
            mention = owner.mention if owner else "Автор тикета"
            await channel.send(
                content=f"{mention}, ваш тикет открыт — им занимается {member.mention}.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        await self._log(
            guild, f"🙋 Тикет **#{ticket.number:04d}** взят в работу — {member.mention}"
        )

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        guild, member = interaction.guild, interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        ticket = await self._require_ticket(interaction)
        if ticket is None:
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        if not is_support(member, config.support_role_id) and member.id != ticket.owner_id:
            await self._reply(
                interaction, "❌ Закрыть тикет может поддержка или его автор."
            )
            return
        if not await self.bot.db.close_ticket(ticket.channel_id):
            await self._reply(interaction, "ℹ️ Тикет уже закрыт.")
            return

        # This runs both from the panel button and from /ticket close, and the
        # two need different responses: a component interaction carries the
        # panel in interaction.message and can update it in place, whereas the
        # slash command has no panel to edit and must answer for itself.
        from_panel = interaction.message is not None
        if from_panel:
            await interaction.response.defer()
        else:
            await self._reply(interaction, "✅ Тикет закрыт.", accent=0xED4245)

        owner = guild.get_member(ticket.owner_id)
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            if owner is not None:
                try:
                    await channel.set_permissions(
                        owner, overwrite=None, reason="Тикет закрыт"
                    )
                except discord.HTTPException:
                    logger.warning("Could not revoke the author's access", exc_info=True)
            new_name = f"closed-{channel.name.removeprefix('claimed-')}"
            try:
                await channel.edit(name=new_name[:100])
            except discord.HTTPException:
                logger.debug("Could not rename the closed ticket", exc_info=True)

        if from_panel:
            claimed = guild.get_member(ticket.claimed_by) if ticket.claimed_by else None
            try:
                await interaction.edit_original_response(
                    view=TicketControls(
                        self,
                        number=ticket.number,
                        owner=owner,
                        category=ticket.category,
                        subject=ticket.subject or "",
                        claimed_by=claimed,
                        closed=True,
                    )
                )
            except discord.HTTPException:
                logger.debug("Could not refresh the ticket panel", exc_info=True)

        if isinstance(channel, discord.abc.Messageable):
            await channel.send(
                view=notice(
                    f"🔒 Тикет закрыт пользователем {member.mention}.", accent=0xED4245
                )
            )
        await self._log(
            guild, f"🔒 Тикет **#{ticket.number:04d}** закрыт — {member.mention}"
        )

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #
    group = app_commands.Group(
        name="ticket",
        description="Панель правил и система обращений",
        guild_only=True,
    )
    config_group = app_commands.Group(
        name="config",
        description="Настройка системы тикетов (нужны права «Управление сервером»)",
        parent=group,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @group.command(name="panel", description="Опубликовать сообщение с правилами и кнопками")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.TextChannel):
            return
        if not channel.permissions_for(guild.me).send_messages:
            await self._reply(interaction, "❌ У бота нет прав писать в этот канал.")
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        # Respond first: publishing can outlast the 3-second interaction window.
        await self._reply(interaction, "✅ Панель опубликована.", accent=0x57F287)
        await channel.send(
            view=RulesPanel(
                self,
                rules_text=config.rules_text,
                icon_url=guild.icon.url if guild.icon else None,
            )
        )

    @group.command(name="close", description="Закрыть текущий тикет")
    @guild_authorized()
    async def close_command(self, interaction: discord.Interaction) -> None:
        await self.close_ticket(interaction)

    @group.command(name="add", description="Добавить участника в текущий тикет")
    @app_commands.describe(user="Кого пригласить в обсуждение")
    @guild_authorized()
    async def add_member(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        guild = interaction.guild
        member = interaction.user
        channel = interaction.channel
        if guild is None or not isinstance(member, discord.Member):
            return
        ticket = await self._require_ticket(interaction)
        if ticket is None:
            return
        config = await self.bot.db.get_ticket_config(guild.id)
        if not is_support(member, config.support_role_id):
            await self._reply(interaction, "❌ Приглашать в тикет может только поддержка.")
            return
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            await channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason=f"Добавлен в тикет по запросу {member}",
            )
        except discord.Forbidden:
            await self._reply(interaction, "❌ У бота нет прав менять доступ к каналу.")
            return
        await self._reply(
            interaction, f"✅ {user.mention} добавлен в тикет.", accent=0x57F287
        )

    # --- configuration --------------------------------------------------- #
    @config_group.command(name="show", description="Показать настройки тикетов")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_show(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        config = await self.bot.db.get_ticket_config(guild.id)

        def show(kind: str, value: int | None) -> str:
            if value is None:
                return "не задано"
            return f"<#{value}>" if kind == "channel" else f"<@&{value}>"

        lines = [
            f"**Категория тикетов:** {show('channel', config.category_id)}",
            f"**Роль поддержки:** {show('role', config.support_role_id)}",
            f"**Роль верификации:** {show('role', config.verify_role_id)}",
            f"**Канал логов:** {show('channel', config.log_channel_id)}",
            f"**Текст правил:** {'свой' if config.rules_text else 'по умолчанию'}",
            "",
            "✅ Готово к работе" if config.tickets_ready else "⚠️ Нужны категория и роль поддержки",
        ]
        await self._reply(interaction, "## 🎫 Настройки тикетов\n" + "\n".join(lines))

    @config_group.command(name="category", description="Категория для каналов тикетов")
    @app_commands.describe(category="Категория; пусто — сбросить")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_category(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        await self.bot.db.update_ticket_config(
            interaction.guild.id, category_id=category.id if category else None
        )
        target = f"**{category.name}**" if category else "сброшена"
        await self._reply(interaction, f"✅ Категория тикетов: {target}", accent=0x57F287)

    @config_group.command(name="support-role", description="Роль, которая видит тикеты")
    @app_commands.describe(role="Роль поддержки; пусто — сбросить")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_support_role(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        if interaction.guild is None:
            return
        await self.bot.db.update_ticket_config(
            interaction.guild.id, support_role_id=role.id if role else None
        )
        await self._reply(
            interaction,
            f"✅ Роль поддержки: {role.mention if role else 'сброшена'}",
            accent=0x57F287,
        )

    @config_group.command(name="verify-role", description="Роль, выдаваемая по кнопке «Согласен»")
    @app_commands.describe(role="Роль верификации; пусто — сбросить")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_verify_role(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if role is not None and role >= guild.me.top_role:
            await self._reply(
                interaction,
                f"❌ {role.mention} выше роли бота — выдать её бот не сможет.\n"
                "Поднимите роль бота в настройках сервера.",
            )
            return
        await self.bot.db.update_ticket_config(
            guild.id, verify_role_id=role.id if role else None
        )
        await self._reply(
            interaction,
            f"✅ Роль верификации: {role.mention if role else 'сброшена'}",
            accent=0x57F287,
        )

    @config_group.command(name="log", description="Канал для журнала тикетов")
    @app_commands.describe(channel="Канал; пусто — выключить журнал")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_log(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        await self.bot.db.update_ticket_config(
            interaction.guild.id, log_channel_id=channel.id if channel else None
        )
        await self._reply(
            interaction,
            f"✅ Журнал тикетов: {channel.mention if channel else 'выключен'}",
            accent=0x57F287,
        )

    @config_group.command(name="rules", description="Задать свой текст правил")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_rules(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        config = await self.bot.db.get_ticket_config(interaction.guild.id)
        await interaction.response.send_modal(RulesModal(self, config.rules_text))

    # ------------------------------------------------------------------ #
    #  Housekeeping
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Drop the row when a ticket channel is deleted by hand."""
        await self.bot.db.delete_ticket(channel.id)


class RulesModal(discord.ui.Modal, title="Текст правил"):
    """Edits the guild's rules text; Markdown is rendered by the panel."""

    text: discord.ui.Label = discord.ui.Label(
        text="Правила",
        description="Markdown поддерживается. Очистите поле, чтобы вернуть текст по умолчанию.",
        component=discord.ui.TextInput(
            custom_id="rules_text",
            style=discord.TextStyle.long,
            max_length=4000,
            required=False,
        ),
    )

    def __init__(self, cog: Tickets, current: str | None) -> None:
        super().__init__()
        self.cog = cog
        component = self.text.component
        assert isinstance(component, discord.ui.TextInput)
        component.default = current or DEFAULT_RULES

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        component = self.text.component
        assert isinstance(component, discord.ui.TextInput)
        value = component.value.strip()
        await self.cog.bot.db.update_ticket_config(
            interaction.guild.id, rules_text=value or None
        )
        await self.cog._reply(
            interaction,
            "✅ Текст правил обновлён." if value else "✅ Возвращён текст по умолчанию.",
            accent=0x57F287,
        )


async def setup(bot: MusicBot) -> None:
    cog = Tickets(bot)
    await bot.add_cog(cog)
    # Register the persistent panels so buttons on messages posted before this
    # restart keep working. Only the custom_ids matter for dispatch; the text
    # shown here is never displayed.
    bot.add_view(RulesPanel(cog))
    bot.add_view(TicketControls(cog))
