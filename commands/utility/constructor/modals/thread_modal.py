"""
Модальное окно для настройки треда.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView


class ThreadNameModal(ui.Modal, title="Настройка треда"):
    """Модальное окно для ввода названия треда."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view

        # Дефолтное название из заголовка embed
        if view.embed.title:
            self.thread_name.default = f"Обсуждение: {view.embed.title[:80]}"

    thread_name = ui.TextInput(
        label="Название треда",
        placeholder="Обсуждение анонса",
        max_length=100,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.view.thread_name = self.thread_name.value
        self.view.create_thread = True

        await interaction.response.send_message(
            f"🧵 Тред будет создан: **{self.thread_name.value}**",
            ephemeral=True,
            delete_after=5
        )
