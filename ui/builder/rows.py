"""Button rows of the builder panel.

Each row is a Components V2 ``ActionRow``; ``self.view`` is the builder that
owns it, which is how a row reaches the shared :class:`BuilderState`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from ui.builder.colors import PRESET_COLORS
from ui.builder.fields import FieldPickerView, ReorderFieldsView
from ui.builder.images import ImageActionView
from ui.builder.modals import (
    AuthorModal,
    ContentModal,
    FieldModal,
    FooterModal,
    MainSettingsModal,
)
from ui.builder.state import BuilderError
from ui.v2 import send_panel

if TYPE_CHECKING:
    from ui.builder.panel import GigaBuilderView


def builder_of(row: ui.ActionRow[GigaBuilderView]) -> GigaBuilderView:
    """The builder this row belongs to (a row is always inside one)."""
    view = row.view
    assert view is not None
    return view


async def _reject(interaction: discord.Interaction, error: BuilderError) -> None:
    await interaction.response.send_message(str(error), ephemeral=True)


class ContentRow(ui.ActionRow["GigaBuilderView"]):
    @ui.button(label="Основное", emoji="📝", style=discord.ButtonStyle.primary)
    async def main_settings(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(MainSettingsModal(builder_of(self)))

    @ui.button(label="Автор", emoji="✍️", style=discord.ButtonStyle.secondary)
    async def author(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(AuthorModal(builder_of(self)))

    @ui.button(label="Футер", emoji="🦶", style=discord.ButtonStyle.secondary)
    async def footer(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(FooterModal(builder_of(self)))

    @ui.button(label="Текст над постом", emoji="💬", style=discord.ButtonStyle.secondary)
    async def content(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(ContentModal(builder_of(self)))


class ColorRow(ui.ActionRow["GigaBuilderView"]):
    @ui.select(
        placeholder="🎨 Выбрать готовый цвет…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=name, value=name, emoji="🎨")
            for name in PRESET_COLORS
        ],
    )
    async def color(self, interaction: discord.Interaction, select: ui.Select) -> None:
        builder = builder_of(self)
        builder.state.embed.colour = PRESET_COLORS[select.values[0]]
        await interaction.response.defer()
        await builder.update_preview()


class MediaRow(ui.ActionRow["GigaBuilderView"]):
    @ui.button(label="Изображение", emoji="🖼️", style=discord.ButtonStyle.secondary)
    async def image(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await send_panel(
            interaction, ImageActionView(builder_of(self), "image"), ephemeral=True
        )

    @ui.button(label="Миниатюра", emoji="📌", style=discord.ButtonStyle.secondary)
    async def thumbnail(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await send_panel(
            interaction, ImageActionView(builder_of(self), "thumbnail"), ephemeral=True
        )


class FieldRow(ui.ActionRow["GigaBuilderView"]):
    @ui.button(label="Добавить поле", emoji="➕", style=discord.ButtonStyle.success)
    async def add_field(self, interaction: discord.Interaction, _: ui.Button) -> None:
        builder = builder_of(self)
        try:
            builder.state.ensure_room()
        except BuilderError as error:
            await _reject(interaction, error)
            return
        await interaction.response.send_modal(FieldModal(builder))

    @ui.button(label="Изменить/Удалить", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_field(self, interaction: discord.Interaction, _: ui.Button) -> None:
        builder = builder_of(self)
        if not builder.state.field_count:
            await interaction.response.send_message("Нет полей.", ephemeral=True)
            return
        await send_panel(interaction, FieldPickerView(builder), ephemeral=True)

    @ui.button(label="Порядок полей", emoji="⇅", style=discord.ButtonStyle.secondary)
    async def reorder(self, interaction: discord.Interaction, _: ui.Button) -> None:
        builder = builder_of(self)
        if builder.state.field_count < 2:
            await interaction.response.send_message(
                "Нужно минимум 2 поля.", ephemeral=True
            )
            return
        await send_panel(interaction, ReorderFieldsView(builder), ephemeral=True)

    @ui.button(label="Разделитель", emoji="➖", style=discord.ButtonStyle.secondary)
    async def separator(self, interaction: discord.Interaction, _: ui.Button) -> None:
        builder = builder_of(self)
        try:
            builder.state.add_separator()
        except BuilderError as error:
            await _reject(interaction, error)
            return
        await interaction.response.defer()
        await builder.update_preview()


class PublishRow(ui.ActionRow["GigaBuilderView"]):
    def __init__(self, publish_format: str) -> None:
        super().__init__()
        self.switch_format.label = (
            "Формат: эмбед" if publish_format == "embed" else "Формат: контейнер V2"
        )

    @ui.button(label="Опубликовать", emoji="✅", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await builder_of(self).publish(interaction)

    @ui.button(label="Формат", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def switch_format(self, interaction: discord.Interaction, _: ui.Button) -> None:
        builder = builder_of(self)
        builder.state.publish_format = (
            "v2" if builder.state.publish_format == "embed" else "embed"
        )
        await interaction.response.defer()
        await builder.update_preview()

    @ui.button(label="Отменить", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await builder_of(self).finish(interaction, "❌ Конструктор закрыт.")
