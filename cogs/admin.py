"""The /announce command: a quick announcement with a preview step."""

from __future__ import annotations

import contextlib
import logging
import re

import discord
from discord import TextStyle, app_commands, ui
from discord.ext import commands

from core.bot import MusicBot
from core.constants import PREVIEW_TIMEOUT
from ui.views import disable_all
from utils.checks import can_announce
from utils.mentions import mentions_for_role
from utils.validation import is_http_url

logger = logging.getLogger("bot.admin")

DEFAULT_ANNOUNCE_TITLE = "📢 Официальное объявление"


def parse_hex_color(value: str) -> int | None:
    """``#RGB`` / ``#RRGGBB`` -> an int, or ``None`` if it is not a hex colour.

    The short form must be expanded first: ``int("f00", 16)`` is 0x000F00
    (dark green), not the red the user asked for.
    """
    if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}){1,2}", value or ""):
        return None
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return int(digits, 16)


class AnnouncePreviewView(ui.View):
    def __init__(
        self,
        embed: discord.Embed,
        target_channel: discord.TextChannel,
        mention: str | None,
        allowed_mentions: discord.AllowedMentions,
    ) -> None:
        super().__init__(timeout=PREVIEW_TIMEOUT)
        self.embed = embed
        self.target_channel = target_channel
        self.mention = mention
        self.allowed_mentions = allowed_mentions

    @ui.button(label="✅ Отправить", style=discord.ButtonStyle.green)
    async def send_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        # Answer the interaction first: a slow or rate-limited send would
        # otherwise blow the 3-second response window.
        disable_all(self)
        await interaction.response.edit_message(
            content="📨 Отправляю анонс…", view=self
        )

        guild = interaction.guild
        me = guild.me if guild is not None else None
        if me is not None and not self.target_channel.permissions_for(me).send_messages:
            await interaction.edit_original_response(
                content=f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
            self.stop()
            return

        # The role/everyone mention lives in the message content (mentions inside
        # an embed never ping) — this is why announcements actually notify.
        try:
            await self.target_channel.send(
                content=self.mention or None,
                embed=self.embed,
                allowed_mentions=self.allowed_mentions,
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
        except discord.HTTPException:
            logger.exception("Failed to send the announcement")
            await interaction.edit_original_response(
                content="⚠️ Не удалось отправить анонс."
            )
        else:
            await interaction.edit_original_response(
                content="✅ **Анонс успешно отправлен!**"
            )
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        disable_all(self)
        await interaction.response.edit_message(
            content="❌ **Отправка анонса отменена.**", view=self
        )
        self.stop()

    async def on_timeout(self) -> None:
        disable_all(self)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: ui.Item,
    ) -> None:
        logger.error("Announce preview failed", exc_info=error)
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(
                "⚠️ Произошла внутренняя ошибка.", ephemeral=True
            )


class AnnounceModal(ui.Modal, title="Создание нового анонса"):
    def __init__(
        self,
        target_channel: discord.TextChannel,
        role: discord.Role | None,
        image_url: str | None,
        thumbnail_url: str | None,
        default_color: int,
    ) -> None:
        super().__init__()
        self.target_channel = target_channel
        self.role = role
        self.image_url = image_url
        self.thumbnail_url = thumbnail_url
        self.default_color = default_color

    custom_title: ui.TextInput = ui.TextInput(
        label="Заголовок (необязательно)",
        placeholder="Оставьте пустым для стандартного заголовка",
        required=False,
        max_length=256,
    )
    message_input: ui.TextInput = ui.TextInput(
        label="Текст объявления (Markdown)",
        style=TextStyle.paragraph,
        placeholder="Введите ваше объявление здесь...",
        required=True,
        max_length=4000,
    )
    color_hex: ui.TextInput = ui.TextInput(
        label="Цвет в HEX (необязательно)",
        placeholder="Например: #5865F2",
        required=False,
        max_length=7,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.custom_title.value or DEFAULT_ANNOUNCE_TITLE
        parsed = parse_hex_color(self.color_hex.value) if self.color_hex.value else None
        color = parsed if parsed is not None else self.default_color

        embed = discord.Embed(
            title=title, description=self.message_input.value, color=color
        )
        embed.set_footer(
            text=f"Анонс от {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        if is_http_url(self.image_url):
            embed.set_image(url=self.image_url)
        if is_http_url(self.thumbnail_url):
            embed.set_thumbnail(url=self.thumbnail_url)

        # Re-apply the invoker's own permissions: being allowed to run /announce
        # must not grant the ability to ping roles they could not ping themselves.
        allowed = mentions_for_role(interaction.user, self.target_channel, self.role)
        mention = (
            self.role.mention
            if self.role and (allowed.everyone or allowed.roles)
            else None
        )
        view = AnnouncePreviewView(embed, self.target_channel, mention, allowed)
        await interaction.response.send_message(
            "**Предпросмотр анонса.** Всё хорошо? Нажмите «Отправить».",
            embed=embed,
            view=view,
            ephemeral=True,
        )


class Admin(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="announce", description="Создать объявление с предпросмотром"
    )
    @app_commands.describe(
        channel="Канал для отправки (по умолчанию — официальный)",
        mention_role="Роль для упоминания",
        image_url="URL картинки (большое изображение)",
        thumbnail_url="URL маленькой иконки",
    )
    @can_announce()
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        mention_role: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
    ) -> None:
        if interaction.guild is None:  # can_announce() already rejects DMs
            return
        default_id = self.bot.settings.announce_default_channel
        target = channel or (
            interaction.guild.get_channel(default_id) if default_id else None
        )
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Канал для анонса не настроен.", ephemeral=True
            )
            return

        role: discord.Role | None = None
        if mention_role:
            if mention_role.isdigit():
                role = interaction.guild.get_role(int(mention_role))
            else:
                role = discord.utils.get(interaction.guild.roles, name=mention_role)
            if role is None:
                await interaction.response.send_message(
                    "❌ Указанная роль не найдена.", ephemeral=True
                )
                return

        modal = AnnounceModal(
            target, role, image_url, thumbnail_url, self.bot.settings.announce_color
        )
        await interaction.response.send_modal(modal)

    @announce.autocomplete("mention_role")
    async def role_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        current = current.lower()
        user = interaction.user
        channel = interaction.channel
        privileged = (
            isinstance(user, discord.Member)
            and isinstance(channel, discord.abc.GuildChannel)
            and channel.permissions_for(user).mention_everyone
        )
        # Only offer roles this user could actually ping; anything else would be
        # silently dropped by mentions_for_role() at send time.
        return [
            app_commands.Choice(name=role.name, value=str(role.id))
            for role in interaction.guild.roles
            if role.name != "@everyone"
            and current in role.name.lower()
            and (privileged or role.mentionable)
        ][:25]


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Admin(bot))
