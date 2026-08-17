"""The /announce command: a quick announcement with a preview step."""

from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import TextStyle, app_commands, ui
from discord.ext import commands

from core.bot import MusicBot
from core.constants import PREVIEW_TIMEOUT, V2_TEXT_LIMIT
from ui.v2 import PanelView, make_panel, send_panel, split_text
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


def build_announcement(
    *,
    title: str,
    body: str,
    color: int,
    author: discord.abc.User,
    image_url: str | None,
    thumbnail_url: str | None,
) -> ui.Container:
    """The announcement itself, as a v2 container."""
    header = f"## {title}"
    container: ui.Container[Any]
    if is_http_url(thumbnail_url):
        container = ui.Container(
            ui.Section(
                ui.TextDisplay(header),
                accessory=ui.Thumbnail(thumbnail_url or ""),
            ),
            accent_colour=color,
        )
    else:
        container = ui.Container(ui.TextDisplay(header), accent_colour=color)

    for chunk in split_text(body, V2_TEXT_LIMIT - len(header) - 120):
        container.add_item(ui.TextDisplay(chunk))
    if is_http_url(image_url):
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(image_url or "")))
    container.add_item(ui.Separator())
    container.add_item(ui.TextDisplay(f"-# Анонс от {author.display_name}"))
    return container


class AnnouncementPanel(PanelView):
    """What actually gets posted in the target channel."""

    def __init__(self, container: ui.Container, mention: str | None) -> None:
        super().__init__(timeout=None)
        # The ping has to be a TextDisplay: a v2 message has no `content`, and a
        # mention only notifies when it is real text in the message body.
        if mention:
            self.add_item(ui.TextDisplay(mention))
        self.add_item(container)


class AnnounceActions(ui.ActionRow["AnnouncePreviewView"]):
    @ui.button(label="Отправить", emoji="✅", style=discord.ButtonStyle.green)
    async def send_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.publish(interaction)

    @ui.button(label="Отменить", emoji="❌", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.replace(interaction, "❌ **Отправка анонса отменена.**")


class AnnouncePreviewView(PanelView):
    def __init__(
        self,
        container: ui.Container,
        target_channel: discord.TextChannel,
        mention: str | None,
        allowed_mentions: discord.AllowedMentions,
    ) -> None:
        super().__init__(timeout=PREVIEW_TIMEOUT)
        self.container = container
        self.target_channel = target_channel
        self.mention = mention
        self.allowed_mentions = allowed_mentions
        self._build()

    def _build(self) -> None:
        self.clear_items()
        self.add_item(
            make_panel(
                body="**Предпросмотр анонса.** Всё хорошо? Нажмите «Отправить».\n"
                f"-# Канал: {self.target_channel.mention}"
                + (f" · упоминание: {self.mention}" if self.mention else "")
            )
        )
        if self.mention:
            # Shown escaped so the preview does not ping anyone prematurely.
            self.add_item(ui.TextDisplay(f"`{self.mention}`"))
        self.add_item(self.container)
        self.add_item(AnnounceActions())

    async def replace(self, interaction: discord.Interaction, text: str) -> None:
        """Swap the whole preview for a final status line."""
        self.clear_items()
        self.add_item(make_panel(body=text))
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(view=self)
            else:
                await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            logger.debug("Could not update the announce preview", exc_info=True)
        self.stop()

    async def publish(self, interaction: discord.Interaction) -> None:
        # Answer the interaction first: a slow or rate-limited send would
        # otherwise blow the 3-second response window.
        busy = PanelView(timeout=None)
        busy.add_item(make_panel(body="📨 Отправляю анонс…"))
        await interaction.response.edit_message(view=busy)

        guild = interaction.guild
        me = guild.me if guild is not None else None
        if me is not None and not self.target_channel.permissions_for(me).send_messages:
            await self.replace(
                interaction, f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
            return

        try:
            await self.target_channel.send(
                view=AnnouncementPanel(self.container, self.mention),
                allowed_mentions=self.allowed_mentions,
            )
        except discord.Forbidden:
            await self.replace(
                interaction, f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
        except discord.HTTPException:
            logger.exception("Failed to send the announcement")
            await self.replace(interaction, "⚠️ Не удалось отправить анонс.")
        else:
            await self.replace(interaction, "✅ **Анонс успешно отправлен!**")


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

        container = build_announcement(
            title=title,
            body=self.message_input.value,
            color=color,
            author=interaction.user,
            image_url=self.image_url,
            thumbnail_url=self.thumbnail_url,
        )

        # Re-apply the invoker's own permissions: being allowed to run /announce
        # must not grant the ability to ping roles they could not ping themselves.
        allowed = mentions_for_role(interaction.user, self.target_channel, self.role)
        mention = (
            self.role.mention
            if self.role and (allowed.everyone or allowed.roles)
            else None
        )
        view = AnnouncePreviewView(container, self.target_channel, mention, allowed)
        await send_panel(interaction, view, ephemeral=True)


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
