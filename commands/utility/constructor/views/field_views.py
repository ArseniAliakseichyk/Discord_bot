"""
Views для управления полями embed.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .main_view import GigaBuilderView

from ..modals.field_modals import FieldModal

logger = logging.getLogger(__name__)


class FieldSelect(ui.Select):
    """Выпадающий список для выбора поля для редактирования или удаления."""

    def __init__(self, view: 'GigaBuilderView'):
        self.view_ref = view

        options = [
            discord.SelectOption(
                label=f"Поле #{i+1}: {field.name[:80]}",
                value=str(i)
            )
            for i, field in enumerate(view.embed.fields)
        ]

        if not options:
            options.append(discord.SelectOption(
                label="Полей для редактирования нет",
                value="-1",
                emoji="🤷‍♂️"
            ))

        super().__init__(
            placeholder="Выберите поле для редактирования/удаления...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "-1":
            return await interaction.response.send_message(
                "Нет полей для выбора.",
                ephemeral=True
            )

        field_index = int(self.values[0])
        self.view_ref.selected_field_index = field_index

        # Создаём view с кнопками действий
        field_action_view = ui.View(timeout=180)

        edit_button = ui.Button(
            label="Редактировать",
            style=discord.ButtonStyle.primary,
            emoji="✏️"
        )
        delete_button = ui.Button(
            label="Удалить",
            style=discord.ButtonStyle.danger,
            emoji="🗑️"
        )

        async def edit_callback(i: discord.Interaction):
            modal = FieldModal(self.view_ref, is_editing=True)
            await i.response.send_modal(modal)
            try:
                await interaction.delete_original_response()
            except discord.NotFound:
                pass

        async def delete_callback(i: discord.Interaction):
            self.view_ref.embed.remove_field(self.view_ref.selected_field_index)
            await self.view_ref.update_preview()
            try:
                await interaction.delete_original_response()
            except discord.NotFound:
                pass
            await i.response.send_message("✅ Поле удалено.", ephemeral=True, delete_after=3)

        edit_button.callback = edit_callback
        delete_button.callback = delete_callback

        field_action_view.add_item(edit_button)
        field_action_view.add_item(delete_button)

        field_name = self.view_ref.embed.fields[field_index].name
        await interaction.response.send_message(
            f"Выбрано Поле #{field_index + 1}: **{field_name}**.\n"
            "Что вы хотите сделать?",
            view=field_action_view,
            ephemeral=True
        )


class ReorderFieldsView(ui.View):
    """View для изменения порядка полей."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__(timeout=300)
        self.builder_view = builder_view

        field_options = [
            discord.SelectOption(
                label=f"Поле #{i+1}: {f.name[:80]}",
                value=str(i)
            )
            for i, f in enumerate(builder_view.embed.fields)
        ]

        self.from_select = ui.Select(
            placeholder="Какое поле переместить?",
            options=field_options,
            min_values=1,
            max_values=1
        )
        self.to_select = ui.Select(
            placeholder="Переместить ПЕРЕД каким полем?",
            options=field_options,
            min_values=1,
            max_values=1
        )

        self.from_select.callback = self.on_select
        self.to_select.callback = self.on_select

        self.add_item(self.from_select)
        self.add_item(self.to_select)

    async def on_select(self, interaction: discord.Interaction):
        if not self.from_select.values or not self.to_select.values:
            return await interaction.response.defer()

        from_index = int(self.from_select.values[0])
        to_index = int(self.to_select.values[0])

        if from_index == to_index:
            return await interaction.response.send_message(
                "❌ Нельзя переместить поле на его же место.",
                ephemeral=True
            )

        # Перемещаем поле
        fields = list(self.builder_view.embed.fields)
        field_to_move = fields.pop(from_index)
        fields.insert(to_index, field_to_move)

        # Обновляем embed
        self.builder_view.embed.clear_fields()
        for field in fields:
            self.builder_view.embed.add_field(
                name=field.name,
                value=field.value,
                inline=field.inline
            )

        await interaction.response.edit_message(
            content="✅ Порядок полей изменен.",
            view=None
        )
        await self.builder_view.update_preview()
        self.stop()
