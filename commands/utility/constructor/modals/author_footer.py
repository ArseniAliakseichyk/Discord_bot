"""
Модальные окна для автора и футера.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView


class AuthorModal(ui.Modal, title="Настройка автора"):
    """Модальное окно для настройки блока автора."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view

        # Заполняем текущими значениями
        author = view.embed.author
        if author:
            self.name.default = author.name
            self.url.default = author.url
            self.icon_url.default = author.icon_url

    name = ui.TextInput(
        label="Имя автора",
        required=False,
        max_length=256,
        placeholder="Имя, которое будет отображаться"
    )

    url = ui.TextInput(
        label="URL автора (необязательно)",
        required=False,
        placeholder="https://example.com"
    )

    icon_url = ui.TextInput(
        label="URL иконки автора (необязательно)",
        required=False,
        placeholder="https://example.com/avatar.png"
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.name.value:
            self.view.embed.set_author(
                name=self.name.value,
                url=self.url.value or None,
                icon_url=self.icon_url.value or None
            )
        else:
            self.view.embed.remove_author()

        await interaction.response.defer()
        await self.view.update_preview()


class FooterModal(ui.Modal, title="Настройка футера"):
    """Модальное окно для настройки футера."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view

        # Заполняем текущими значениями
        footer = view.embed.footer
        if footer:
            self.text.default = footer.text
            self.icon_url.default = footer.icon_url

    text = ui.TextInput(
        label="Текст футера",
        required=False,
        max_length=2048,
        placeholder="Текст в нижней части embed"
    )

    icon_url = ui.TextInput(
        label="URL иконки футера (необязательно)",
        required=False,
        placeholder="https://example.com/icon.png"
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.text.value:
            self.view.embed.set_footer(
                text=self.text.value,
                icon_url=self.icon_url.value or None
            )
        else:
            self.view.embed.remove_footer()

        await interaction.response.defer()
        await self.view.update_preview()
