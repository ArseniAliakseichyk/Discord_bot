"""Field pickers: choose a field to edit/delete, or reorder the list.

Both views carry the index they act on inside themselves. The previous version
stored it on the builder as ``selected_field_index``, so a second picker opened
before the first was answered silently redirected the edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from core.constants import IMAGE_ACTION_TIMEOUT, PREVIEW_TIMEOUT, SELECT_LABEL_LIMIT
from ui.builder.modals import FieldModal
from ui.builder.state import BuilderError
from ui.v2 import PanelView, as_select, make_panel

if TYPE_CHECKING:
    from ui.builder.panel import GigaBuilderView


def _field_options(view: GigaBuilderView) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=label[:SELECT_LABEL_LIMIT], value=str(index))
        for index, label in enumerate(view.state.field_labels())
    ]


class FieldPickerRow(ui.ActionRow["FieldPickerView"]):
    def __init__(self, view: GigaBuilderView) -> None:
        super().__init__()
        as_select(self.pick).options = _field_options(view)

    @ui.select(placeholder="Выберите поле…", min_values=1, max_values=1, options=[])
    async def pick(self, interaction: discord.Interaction, select: ui.Select) -> None:
        view = self.view
        assert view is not None
        await view.show_actions(interaction, int(select.values[0]))


class FieldActionRow(ui.ActionRow["FieldPickerView"]):
    """Edit/delete for one specific field index."""

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index

    @ui.button(label="Редактировать", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await interaction.response.send_modal(FieldModal(view.builder, self.index))
        await view.close()

    @ui.button(label="Удалить", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        try:
            view.builder.state.remove_field(self.index)
        except BuilderError as error:
            await view.replace(interaction, str(error))
            return
        await view.replace(interaction, f"🗑️ Поле #{self.index + 1} удалено.")
        await view.builder.update_preview()


class FieldPickerView(PanelView):
    def __init__(self, builder: GigaBuilderView) -> None:
        super().__init__(timeout=IMAGE_ACTION_TIMEOUT)
        self.builder = builder
        self.add_item(make_panel(body="Выберите поле для редактирования или удаления:"))
        self.add_item(FieldPickerRow(builder))

    async def show_actions(self, interaction: discord.Interaction, index: int) -> None:
        labels = self.builder.state.field_labels()
        if not 0 <= index < len(labels):
            await self.replace(interaction, "❌ Этого поля больше нет.")
            return
        self.clear_items()
        self.add_item(make_panel(body=f"Выбрано **{labels[index]}**.\nЧто сделать?"))
        self.add_item(FieldActionRow(index))
        await interaction.response.edit_message(view=self)

    async def replace(self, interaction: discord.Interaction, text: str) -> None:
        self.clear_items()
        self.add_item(make_panel(body=text))
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(view=self)
            else:
                await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        self.stop()

    async def close(self) -> None:
        """Used after opening a modal, where the response is already consumed."""
        self.clear_items()
        self.add_item(make_panel(body="✏️ Открыта форма редактирования…"))
        if self._origin is not None:
            try:
                await self._origin.edit_original_response(view=self)
            except discord.HTTPException:
                pass
        self.stop()


class ReorderRow(ui.ActionRow["ReorderFieldsView"]):
    def __init__(self, view: GigaBuilderView, *, target: bool) -> None:
        super().__init__()
        self.target = target
        as_select(self.pick).options = _field_options(view)
        as_select(self.pick).placeholder = (
            "Переместить ПЕРЕД каким полем?" if target else "Какое поле переместить?"
        )

    @ui.select(min_values=1, max_values=1, options=[])
    async def pick(self, interaction: discord.Interaction, select: ui.Select) -> None:
        view = self.view
        assert view is not None
        if self.target:
            view.before = int(select.values[0])
        else:
            view.source = int(select.values[0])
        await view.try_apply(interaction)


class ReorderFieldsView(PanelView):
    def __init__(self, builder: GigaBuilderView) -> None:
        super().__init__(timeout=PREVIEW_TIMEOUT)
        self.builder = builder
        self.source: int | None = None
        self.before: int | None = None
        self.add_item(
            make_panel(
                title="⇅ Порядок полей",
                body="Выберите поле и позицию, перед которой его поставить.",
            )
        )
        self.add_item(ReorderRow(builder, target=False))
        self.add_item(ReorderRow(builder, target=True))

    async def try_apply(self, interaction: discord.Interaction) -> None:
        if self.source is None or self.before is None:
            # Only one half chosen so far — keep the menu open.
            await interaction.response.defer()
            return
        try:
            self.builder.state.move_field(self.source, self.before)
        except BuilderError as error:
            await self.replace(interaction, str(error))
            return
        await self.replace(interaction, "✅ Порядок полей изменён.")
        await self.builder.update_preview()

    async def replace(self, interaction: discord.Interaction, text: str) -> None:
        self.clear_items()
        self.add_item(make_panel(body=text))
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        self.stop()
