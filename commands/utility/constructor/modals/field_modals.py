"""
Модальное окно для настройки полей embed.
"""
import discord
from discord import ui, TextStyle
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView


class FieldModal(ui.Modal, title="Настройка поля"):
    """Модальное окно для добавления/редактирования поля."""

    def __init__(self, view: 'GigaBuilderView', is_editing: bool = False):
        super().__init__()
        self.view = view
        self.is_editing = is_editing

        # Если редактирование - заполняем текущими значениями
        if is_editing and view.selected_field_index is not None:
            field = view.embed.fields[view.selected_field_index]
            self.name.default = field.name
            self.value.default = field.value
            self.is_inline_input.default = "да" if field.inline else "нет"
        else:
            self.is_inline_input.default = "нет"

    name = ui.TextInput(
        label="Заголовок поля",
        max_length=256,
        required=True,
        placeholder="Название поля"
    )

    value = ui.TextInput(
        label="Текст поля",
        style=TextStyle.paragraph,
        max_length=1024,
        required=True,
        placeholder="Содержимое поля"
    )

    is_inline_input = ui.TextInput(
        label="В одну линию? (да/нет)",
        placeholder="нет",
        required=False,
        max_length=3,
        row=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        is_inline = self.is_inline_input.value.lower().strip() == 'да'

        if self.is_editing and self.view.selected_field_index is not None:
            # Редактирование существующего поля
            self.view.embed.set_field_at(
                self.view.selected_field_index,
                name=self.name.value,
                value=self.value.value,
                inline=is_inline
            )
        else:
            # Добавление нового поля
            self.view.embed.add_field(
                name=self.name.value,
                value=self.value.value,
                inline=is_inline
            )

        await interaction.response.defer()
        await self.view.update_preview()
