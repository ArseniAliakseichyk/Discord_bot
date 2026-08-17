"""Modal forms for the announcement builder.

Each modal validates its input **before** touching the state, so a rejected form
never leaves the embed half-updated, and every one refreshes the preview on
success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import TextStyle, ui

from ui.builder.colors import parse_hex_color
from ui.builder.state import (
    MAX_DESCRIPTION,
    MAX_FIELD_NAME,
    MAX_FIELD_VALUE,
    MAX_FOOTER,
    MAX_TITLE,
    BuilderError,
)
from utils.validation import is_http_url

if TYPE_CHECKING:
    from ui.builder.panel import GigaBuilderView

#: Accepted spellings for the yes/no text inputs.
_YES = {"да", "yes", "y", "1", "+", "true"}


def _is_yes(value: str) -> bool:
    return value.strip().lower() in _YES


async def _fail(interaction: discord.Interaction, message: str) -> None:
    await interaction.response.send_message(message, ephemeral=True)


class FieldModal(ui.Modal, title="Настройка поля"):
    """Add a field, or edit the one at ``index``.

    ``index`` is captured when the modal opens instead of being read from
    shared view state at submit time — otherwise opening a second picker in the
    meantime would redirect this edit to a different field.
    """

    name: ui.TextInput = ui.TextInput(
        label="Заголовок поля", max_length=MAX_FIELD_NAME, required=True
    )
    value: ui.TextInput = ui.TextInput(
        label="Текст поля",
        style=TextStyle.paragraph,
        max_length=MAX_FIELD_VALUE,
        required=True,
    )
    is_inline_input: ui.TextInput = ui.TextInput(
        label="В одну линию? (да/нет)", placeholder="нет", required=False, max_length=3
    )

    def __init__(self, view: GigaBuilderView, index: int | None = None) -> None:
        super().__init__()
        self.view = view
        self.index = index
        if index is not None and 0 <= index < view.state.field_count:
            existing = view.state.embed.fields[index]
            self.name.default = existing.name
            self.value.default = existing.value
            self.is_inline_input.default = "да" if existing.inline else "нет"
        else:
            self.is_inline_input.default = "нет"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        inline = _is_yes(self.is_inline_input.value)
        try:
            if self.index is None:
                self.view.state.add_field(
                    self.name.value, self.value.value, inline=inline
                )
            else:
                self.view.state.set_field(
                    self.index, self.name.value, self.value.value, inline=inline
                )
        except BuilderError as error:
            await _fail(interaction, str(error))
            return
        await interaction.response.defer()
        await self.view.update_preview()


class MainSettingsModal(ui.Modal, title="Основные настройки"):
    title_input: ui.TextInput = ui.TextInput(
        label="Заголовок", required=False, max_length=MAX_TITLE
    )
    title_url_input: ui.TextInput = ui.TextInput(
        label="URL заголовка (необязательно)", required=False
    )
    description_input: ui.TextInput = ui.TextInput(
        label="Описание", style=TextStyle.paragraph, required=False, max_length=MAX_DESCRIPTION
    )
    color_input: ui.TextInput = ui.TextInput(
        label="Цвет (HEX, #ff00ff; пусто — убрать)",
        required=False,
        max_length=7,
        placeholder="#008080",
    )
    timestamp_input: ui.TextInput = ui.TextInput(
        label="Включить время? (да/нет)", placeholder="нет", required=False, max_length=3
    )

    def __init__(self, view: GigaBuilderView) -> None:
        super().__init__()
        self.view = view
        embed = view.state.embed
        self.title_input.default = embed.title
        self.title_url_input.default = embed.url
        self.description_input.default = embed.description
        if embed.colour:
            self.color_input.default = f"#{embed.colour.value:06x}"
        self.timestamp_input.default = "да" if embed.timestamp else "нет"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_color = self.color_input.value.strip()
        color: discord.Color | None = None
        if raw_color:
            color = parse_hex_color(raw_color)
            # Validate first: the previous version wrote the title and
            # description before parsing the colour, so a typo left the embed
            # partly changed while the preview still showed the old values.
            if color is None:
                await _fail(
                    interaction, "❌ Неверный HEX-цвет! Формат `#RRGGBB` или `#RGB`."
                )
                return

        url = self.title_url_input.value.strip()
        if url and not is_http_url(url):
            await _fail(interaction, "❌ URL заголовка должен начинаться с http/https.")
            return

        self.view.state.apply_main(
            title=self.title_input.value,
            url=url,
            description=self.description_input.value,
            color=color,
            # An emptied colour field now really clears the colour; before, the
            # whole branch was skipped and the old colour silently stayed.
            clear_color=not raw_color,
            timestamp=_is_yes(self.timestamp_input.value),
        )
        await interaction.response.defer()
        await self.view.update_preview()


class ContentModal(ui.Modal, title="Текст сообщения"):
    content_input: ui.TextInput = ui.TextInput(
        label="Текст над постом",
        style=TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Здесь можно упомянуть @роль или @everyone...",
    )

    def __init__(self, view: GigaBuilderView) -> None:
        super().__init__()
        self.view = view
        self.content_input.default = view.state.message_content

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view.state.message_content = self.content_input.value or None
        # This modal used to skip the refresh, so the panel kept showing the
        # previous text until some other button happened to redraw it.
        await interaction.response.defer()
        await self.view.update_preview()


class AuthorModal(ui.Modal, title="Настройка автора"):
    name: ui.TextInput = ui.TextInput(
        label="Имя автора", required=False, max_length=MAX_TITLE
    )
    url: ui.TextInput = ui.TextInput(label="URL автора (необязательно)", required=False)
    icon_url: ui.TextInput = ui.TextInput(
        label="URL иконки автора (необязательно)", required=False
    )

    def __init__(self, view: GigaBuilderView) -> None:
        super().__init__()
        self.view = view
        author = view.state.embed.author
        if author:
            self.name.default = author.name
            self.url.default = author.url
            self.icon_url.default = author.icon_url

    async def on_submit(self, interaction: discord.Interaction) -> None:
        icon = self.icon_url.value.strip()
        if icon and not is_http_url(icon):
            await _fail(interaction, "❌ URL иконки должен начинаться с http/https.")
            return
        if self.name.value:
            self.view.state.embed.set_author(
                name=self.name.value,
                url=self.url.value or None,
                icon_url=icon or None,
            )
        else:
            self.view.state.embed.remove_author()
        await interaction.response.defer()
        await self.view.update_preview()


class FooterModal(ui.Modal, title="Настройка футера"):
    text: ui.TextInput = ui.TextInput(
        label="Текст футера", required=False, max_length=MAX_FOOTER
    )
    icon_url: ui.TextInput = ui.TextInput(
        label="URL иконки футера (необязательно)", required=False
    )

    def __init__(self, view: GigaBuilderView) -> None:
        super().__init__()
        self.view = view
        footer = view.state.embed.footer
        if footer:
            self.text.default = footer.text
            self.icon_url.default = footer.icon_url

    async def on_submit(self, interaction: discord.Interaction) -> None:
        icon = self.icon_url.value.strip()
        if icon and not is_http_url(icon):
            await _fail(interaction, "❌ URL иконки должен начинаться с http/https.")
            return
        if self.text.value:
            self.view.state.embed.set_footer(text=self.text.value, icon_url=icon or None)
        else:
            self.view.state.embed.remove_footer()
        await interaction.response.defer()
        await self.view.update_preview()


class ImageModal(ui.Modal, title="Изображение по URL"):
    url: ui.TextInput = ui.TextInput(label="URL изображения", required=False)

    def __init__(self, view: GigaBuilderView, kind: str) -> None:
        super().__init__()
        self.view = view
        self.kind = kind
        self.url.default = view.state.media_url(kind)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.url.value.strip()
        if value and not is_http_url(value):
            await _fail(
                interaction, "❌ Это не похоже на корректный URL (http/https)."
            )
            return
        self.view.state.set_media(self.kind, value or None)
        await interaction.response.defer()
        await self.view.update_preview()
