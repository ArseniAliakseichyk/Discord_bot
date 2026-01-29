"""
Основные модальные окна: настройки embed и текст сообщения.
"""
import discord
from discord import ui, TextStyle
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView


class MainSettingsModal(ui.Modal, title="Основные настройки"):
    """Модальное окно для заголовка, описания, цвета и URL."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view

        # Заполняем значениями по умолчанию
        self.title_input.default = view.embed.title
        self.title_url_input.default = view.embed.url
        self.description_input.default = view.embed.description

        if view.embed.color:
            self.color_input.default = f"#{view.embed.color.value:06x}"

        self.timestamp_input.default = "да" if view.embed.timestamp else "нет"

    title_input = ui.TextInput(
        label="Заголовок",
        required=False,
        max_length=256,
        placeholder="Заголовок embed"
    )

    title_url_input = ui.TextInput(
        label="URL для заголовка (необязательно)",
        required=False,
        placeholder="https://example.com"
    )

    description_input = ui.TextInput(
        label="Описание",
        style=TextStyle.paragraph,
        required=False,
        max_length=4000,
        placeholder="Основной текст embed"
    )

    color_input = ui.TextInput(
        label="Цвет (HEX, например #ff00ff)",
        required=False,
        max_length=7,
        placeholder="#008080"
    )

    timestamp_input = ui.TextInput(
        label="Включить время? (да/нет)",
        placeholder="нет",
        required=False,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.view.embed.title = self.title_input.value or None
        self.view.embed.url = self.title_url_input.value or None
        self.view.embed.description = self.description_input.value or None

        # Обработка цвета
        if self.color_input.value:
            try:
                hex_color = self.color_input.value.strip().lstrip("#")
                if len(hex_color) == 0:
                    self.view.embed.color = None
                else:
                    self.view.embed.color = discord.Color(int(hex_color, 16))
            except ValueError:
                await interaction.response.send_message(
                    "❌ Неверный формат цвета HEX! Используйте формат `#RRGGBB`.",
                    ephemeral=True
                )
                return

        # Обработка timestamp
        if self.timestamp_input.value.lower().strip() == 'да':
            self.view.embed.timestamp = discord.utils.utcnow()
        else:
            self.view.embed.timestamp = None

        await interaction.response.defer()
        await self.view.update_preview()


class ContentModal(ui.Modal, title="Текст сообщения"):
    """Модальное окно для текста над embed."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view
        self.content_input.default = view.message_content

    content_input = ui.TextInput(
        label="Текст над эмбедом",
        style=TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Здесь можно упомянуть @роль или @everyone..."
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.view.message_content = self.content_input.value or None
        await interaction.response.send_message(
            "✅ Текст сообщения обновлен.",
            ephemeral=True,
            delete_after=5
        )
