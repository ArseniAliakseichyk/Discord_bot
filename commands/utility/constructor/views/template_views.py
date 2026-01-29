"""
Views для работы с шаблонами.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .main_view import GigaBuilderView

from ..utils.templates import (
    save_template, load_template, list_templates,
    delete_template, DEFAULT_TEMPLATES, get_default_template
)

logger = logging.getLogger(__name__)


class TemplateActionView(ui.View):
    """View для выбора действия с шаблонами."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__(timeout=180)
        self.builder_view = builder_view

    @ui.button(label="💾 Сохранить", style=discord.ButtonStyle.success, emoji="💾")
    async def save_template_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SaveTemplateModal(self.builder_view))
        self.stop()

    @ui.button(label="📂 Загрузить", style=discord.ButtonStyle.primary, emoji="📂")
    async def load_template_btn(self, interaction: discord.Interaction, button: ui.Button):
        templates = list_templates()
        default_names = list(DEFAULT_TEMPLATES.keys())

        if not templates and not default_names:
            return await interaction.response.send_message(
                "📂 Нет сохранённых шаблонов.",
                ephemeral=True
            )

        view = LoadTemplateView(self.builder_view, templates, default_names)
        await interaction.response.edit_message(
            content="📂 **Выберите шаблон для загрузки:**",
            view=view
        )

    @ui.button(label="🗑️ Удалить", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_template_btn(self, interaction: discord.Interaction, button: ui.Button):
        templates = list_templates()

        if not templates:
            return await interaction.response.send_message(
                "📂 Нет сохранённых шаблонов для удаления.",
                ephemeral=True
            )

        view = DeleteTemplateView(templates)
        await interaction.response.edit_message(
            content="🗑️ **Выберите шаблон для удаления:**",
            view=view
        )


class SaveTemplateModal(ui.Modal, title="Сохранить шаблон"):
    """Модальное окно для сохранения шаблона."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__()
        self.builder_view = builder_view

    name = ui.TextInput(
        label="Название шаблона",
        placeholder="Мой шаблон",
        max_length=50,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        success = save_template(
            name=self.name.value,
            embed=self.builder_view.embed,
            buttons=self.builder_view.custom_buttons,
            message_content=self.builder_view.message_content
        )

        if success:
            await interaction.response.send_message(
                f"✅ Шаблон **{self.name.value}** сохранён!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Не удалось сохранить шаблон.",
                ephemeral=True
            )


class LoadTemplateView(ui.View):
    """View для выбора шаблона для загрузки."""

    def __init__(
        self,
        builder_view: 'GigaBuilderView',
        user_templates: list,
        default_templates: list
    ):
        super().__init__(timeout=180)
        self.builder_view = builder_view

        # Добавляем пользовательские шаблоны
        if user_templates:
            options = [
                discord.SelectOption(
                    label=name[:100],
                    value=f"user:{name}",
                    emoji="📄"
                )
                for name in user_templates[:20]  # Лимит 25 опций
            ]

            user_select = ui.Select(
                placeholder="📄 Ваши шаблоны...",
                options=options,
                min_values=1,
                max_values=1
            )
            user_select.callback = self.on_select
            self.add_item(user_select)

        # Добавляем предустановленные шаблоны
        if default_templates:
            options = [
                discord.SelectOption(
                    label=name,
                    value=f"default:{name}",
                    emoji="⭐"
                )
                for name in default_templates
            ]

            default_select = ui.Select(
                placeholder="⭐ Готовые шаблоны...",
                options=options,
                min_values=1,
                max_values=1
            )
            default_select.callback = self.on_select
            self.add_item(default_select)

    async def on_select(self, interaction: discord.Interaction):
        # Получаем выбранное значение из любого select
        value = None
        for item in self.children:
            if isinstance(item, ui.Select) and item.values:
                value = item.values[0]
                break

        if not value:
            return

        if value.startswith("default:"):
            name = value[8:]
            embed = get_default_template(name)
            if embed:
                self.builder_view.embed = embed
                self.builder_view.custom_buttons = []
                self.builder_view.message_content = None
                await self.builder_view.update_preview()
                await interaction.response.edit_message(
                    content=f"✅ Загружен шаблон: **{name}**",
                    view=None
                )
            else:
                await interaction.response.send_message(
                    "❌ Шаблон не найден.",
                    ephemeral=True
                )
        else:
            name = value[5:]  # Убираем "user:"
            data = load_template(name)
            if data:
                self.builder_view.embed = data["embed"]
                self.builder_view.custom_buttons = data.get("buttons", [])
                self.builder_view.message_content = data.get("message_content")
                await self.builder_view.update_preview()
                await interaction.response.edit_message(
                    content=f"✅ Загружен шаблон: **{name}**",
                    view=None
                )
            else:
                await interaction.response.send_message(
                    "❌ Не удалось загрузить шаблон.",
                    ephemeral=True
                )

        self.stop()


class DeleteTemplateView(ui.View):
    """View для удаления шаблона."""

    def __init__(self, templates: list):
        super().__init__(timeout=180)

        options = [
            discord.SelectOption(label=name[:100], value=name, emoji="📄")
            for name in templates[:25]
        ]

        select = ui.Select(
            placeholder="Выберите шаблон для удаления...",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, ui.Select) and item.values:
                name = item.values[0]
                break
        else:
            return

        success = delete_template(name)

        if success:
            await interaction.response.edit_message(
                content=f"✅ Шаблон **{name}** удалён!",
                view=None
            )
        else:
            await interaction.response.send_message(
                "❌ Не удалось удалить шаблон.",
                ephemeral=True
            )

        self.stop()
