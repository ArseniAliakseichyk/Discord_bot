"""The /announce command: a quick announcement with a preview step."""

from __future__ import annotations

import re

import discord
from discord import TextStyle, app_commands, ui
from discord.ext import commands

from core.bot import MusicBot
from utils.checks import can_announce
from utils.validation import is_http_url

# Mentions are allowed only on the final announcement send.
_ANNOUNCE_MENTIONS = discord.AllowedMentions(everyone=True, roles=True, users=True)


class AnnouncePreviewView(ui.View):
    def __init__(
        self,
        embed: discord.Embed,
        target_channel: discord.TextChannel,
        mention: str | None,
    ) -> None:
        super().__init__(timeout=300)
        self.embed = embed
        self.target_channel = target_channel
        self.mention = mention

    @ui.button(label="✅ Отправить", style=discord.ButtonStyle.green)
    async def send_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        # The role/everyone mention lives in the message content (mentions inside
        # an embed never ping) — this is why announcements now actually notify.
        await self.target_channel.send(
            content=self.mention or None,
            embed=self.embed,
            allowed_mentions=_ANNOUNCE_MENTIONS,
        )
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content="✅ **Анонс успешно отправлен!**", view=self
        )
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, _: ui.Button) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content="❌ **Отправка анонса отменена.**", view=self
        )
        self.stop()


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

    custom_title = ui.TextInput(
        label="Заголовок (необязательно)",
        placeholder="Оставьте пустым для стандартного заголовка",
        required=False,
        max_length=256,
    )
    message_input = ui.TextInput(
        label="Текст объявления (Markdown)",
        style=TextStyle.paragraph,
        placeholder="Введите ваше объявление здесь...",
        required=True,
        max_length=4000,
    )
    color_hex = ui.TextInput(
        label="Цвет в HEX (необязательно)",
        placeholder="Например: #5865F2",
        required=False,
        max_length=7,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.custom_title.value or "📢 Официальное объявление"
        color = self.default_color
        if self.color_hex.value and re.fullmatch(
            r"#(?:[0-9a-fA-F]{3}){1,2}", self.color_hex.value
        ):
            color = int(self.color_hex.value.lstrip("#"), 16)

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

        mention = self.role.mention if self.role else None
        view = AnnouncePreviewView(embed, self.target_channel, mention)
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
        assert interaction.guild is not None
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
        allowed = self.bot.settings.announce_allowed_roles
        current = current.lower()
        return [
            app_commands.Choice(
                name=f"{role.name}{' ✅' if role.id in allowed else ''}",
                value=str(role.id),
            )
            for role in interaction.guild.roles
            if role.name != "@everyone" and current in role.name.lower()
        ][:25]


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Admin(bot))
