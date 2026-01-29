"""
Конструктор кнопок для embed.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING, List, Dict, Any, Optional
import logging

if TYPE_CHECKING:
    from .main_view import GigaBuilderView

from ..constants import BUTTONS_PER_ROW, BUTTON_ROWS_MAX

logger = logging.getLogger(__name__)


class ButtonBuilderView(ui.View):
    """View для управления кнопками."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__(timeout=300)
        self.builder_view = builder_view

    @ui.button(label="➕ Добавить кнопку", style=discord.ButtonStyle.success, emoji="➕")
    async def add_button(self, interaction: discord.Interaction, button: ui.Button):
        total = len(self.builder_view.custom_buttons)
        max_buttons = BUTTONS_PER_ROW * BUTTON_ROWS_MAX

        if total >= max_buttons:
            return await interaction.response.send_message(
                f"❌ Достигнут лимит кнопок ({max_buttons})!",
                ephemeral=True
            )

        await interaction.response.send_modal(ButtonConfigModal(self.builder_view))

    @ui.button(label="📋 Список кнопок", style=discord.ButtonStyle.primary, emoji="📋")
    async def list_buttons(self, interaction: discord.Interaction, button: ui.Button):
        buttons = self.builder_view.custom_buttons

        if not buttons:
            return await interaction.response.send_message(
                "📋 Кнопок пока нет.",
                ephemeral=True
            )

        text = "**📋 Добавленные кнопки:**\n\n"
        for i, btn in enumerate(buttons):
            style_emoji = {
                "primary": "🔵",
                "secondary": "⚪",
                "success": "🟢",
                "danger": "🔴",
                "link": "🔗"
            }.get(btn.get("style", "primary"), "⚪")

            emoji = btn.get("emoji", "")
            label = btn.get("label", "Без названия")
            btn_type = "URL" if btn.get("url") else "Роль" if btn.get("role_id") else "Обычная"

            text += f"{i+1}. {style_emoji} {emoji} **{label}** ({btn_type})\n"

        await interaction.response.send_message(text, ephemeral=True)

    @ui.button(label="🗑️ Удалить кнопку", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        buttons = self.builder_view.custom_buttons

        if not buttons:
            return await interaction.response.send_message(
                "📋 Нет кнопок для удаления.",
                ephemeral=True
            )

        view = DeleteButtonView(self.builder_view)
        await interaction.response.send_message(
            "🗑️ Выберите кнопку для удаления:",
            view=view,
            ephemeral=True
        )

    @ui.button(label="👁️ Превью", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def preview_buttons(self, interaction: discord.Interaction, button: ui.Button):
        buttons = self.builder_view.custom_buttons

        if not buttons:
            return await interaction.response.send_message(
                "📋 Добавьте кнопки для просмотра превью.",
                ephemeral=True
            )

        preview_view = create_button_view(buttons, self.builder_view.client, preview=True)

        await interaction.response.send_message(
            "**👁️ Превью кнопок:**\n*(кнопки в режиме превью не работают)*",
            view=preview_view,
            ephemeral=True
        )


class ButtonConfigModal(ui.Modal, title="Настройка кнопки"):
    """Модальное окно для настройки кнопки."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__()
        self.builder_view = builder_view

    label = ui.TextInput(
        label="Текст кнопки",
        placeholder="Нажми меня!",
        max_length=80,
        required=True
    )

    emoji = ui.TextInput(
        label="Эмодзи (необязательно)",
        placeholder="🎉 или пусто",
        max_length=50,
        required=False
    )

    style = ui.TextInput(
        label="Стиль: primary/secondary/success/danger/link",
        placeholder="primary",
        max_length=10,
        required=False
    )

    url_or_role = ui.TextInput(
        label="URL (для link) или ID роли (для выдачи роли)",
        placeholder="https://... или 123456789",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        style = self.style.value.lower().strip() or "primary"

        if style not in ["primary", "secondary", "success", "danger", "link"]:
            return await interaction.response.send_message(
                "❌ Неверный стиль. Используйте: primary, secondary, success, danger, link",
                ephemeral=True
            )

        button_data = {
            "label": self.label.value,
            "style": style,
            "emoji": self.emoji.value.strip() if self.emoji.value else None
        }

        # Обработка URL или роли
        url_or_role = self.url_or_role.value.strip() if self.url_or_role.value else None

        if style == "link":
            if not url_or_role or not url_or_role.startswith(("http://", "https://")):
                return await interaction.response.send_message(
                    "❌ Для стиля 'link' нужен URL (начинается с http:// или https://)",
                    ephemeral=True
                )
            button_data["url"] = url_or_role
        elif url_or_role and url_or_role.isdigit():
            button_data["role_id"] = int(url_or_role)

        self.builder_view.custom_buttons.append(button_data)

        await interaction.response.send_message(
            f"✅ Кнопка **{self.label.value}** добавлена!",
            ephemeral=True
        )


class DeleteButtonView(ui.View):
    """View для удаления кнопки."""

    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__(timeout=180)
        self.builder_view = builder_view

        buttons = builder_view.custom_buttons
        options = [
            discord.SelectOption(
                label=f"{i+1}. {btn.get('label', 'Без названия')[:50]}",
                value=str(i),
                emoji=btn.get("emoji") or "🔘"
            )
            for i, btn in enumerate(buttons[:25])
        ]

        select = ui.Select(
            placeholder="Выберите кнопку...",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, ui.Select) and item.values:
                index = int(item.values[0])
                break
        else:
            return

        removed = self.builder_view.custom_buttons.pop(index)

        await interaction.response.edit_message(
            content=f"✅ Кнопка **{removed.get('label')}** удалена!",
            view=None
        )
        self.stop()


def create_button_view(
    buttons: List[Dict[str, Any]],
    client: discord.Client,
    preview: bool = False
) -> ui.View:
    """
    Создаёт View с кнопками для публикации.

    Args:
        buttons: Список конфигураций кнопок
        client: Discord клиент (для обработчиков ролей)
        preview: Если True, кнопки будут отключены

    Returns:
        discord.ui.View
    """
    view = ui.View(timeout=None)

    style_map = {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
        "link": discord.ButtonStyle.link
    }

    for i, btn_data in enumerate(buttons[:25]):
        style = style_map.get(btn_data.get("style", "primary"), discord.ButtonStyle.primary)
        label = btn_data.get("label", "Кнопка")
        emoji = btn_data.get("emoji")
        url = btn_data.get("url")
        role_id = btn_data.get("role_id")

        if url:
            # Link button
            button = ui.Button(
                style=discord.ButtonStyle.link,
                label=label,
                emoji=emoji,
                url=url,
                disabled=preview
            )
        else:
            # Regular button
            button = ui.Button(
                style=style,
                label=label,
                emoji=emoji,
                custom_id=f"constructor_btn_{i}",
                disabled=preview
            )

            if role_id and not preview:
                # Создаём callback для выдачи роли
                async def role_callback(
                    interaction: discord.Interaction,
                    rid=role_id
                ):
                    role = interaction.guild.get_role(rid)
                    if not role:
                        return await interaction.response.send_message(
                            "❌ Роль не найдена.",
                            ephemeral=True
                        )

                    member = interaction.user
                    if role in member.roles:
                        await member.remove_roles(role)
                        await interaction.response.send_message(
                            f"➖ Роль **{role.name}** снята.",
                            ephemeral=True
                        )
                    else:
                        await member.add_roles(role)
                        await interaction.response.send_message(
                            f"➕ Роль **{role.name}** выдана!",
                            ephemeral=True
                        )

                button.callback = role_callback

        view.add_item(button)

    return view
