"""
Главная панель конструктора embed (GigaBuilderView).
"""
import discord
from discord import ui
from typing import Optional, List, Dict, Any
import logging
import os

from ..constants import (
    MAIN_VIEW_TIMEOUT, FIELDS_MAX, DEFAULT_EMBED_TITLE,
    DEFAULT_EMBED_DESCRIPTION
)
from ..utils.colors import PRESET_COLORS, parse_text_colors
from ..utils.validators import validate_embed, get_embed_stats, get_warnings
from ..modals.main_modals import MainSettingsModal, ContentModal
from ..modals.author_footer import AuthorModal, FooterModal
from ..modals.field_modals import FieldModal
from .field_views import FieldSelect, ReorderFieldsView
from .image_views import ImageActionView

logger = logging.getLogger(__name__)


class GigaBuilderView(ui.View):
    """
    Главная панель конструктора embed.

    Включает:
    - Настройки embed (заголовок, описание, цвет)
    - Управление полями
    - Изображения
    - Автор и футер
    - Кнопки публикации
    - Шаблоны и планирование (новые функции)
    """

    def __init__(
        self,
        author: discord.User,
        target_channel: discord.TextChannel,
        role_to_mention: Optional[discord.Role],
        client: discord.Client
    ):
        super().__init__(timeout=MAIN_VIEW_TIMEOUT)
        self.author = author
        self.target_channel = target_channel
        self.role_to_mention = role_to_mention
        self.client = client

        # Состояние
        self.message: Optional[discord.InteractionMessage] = None
        self.selected_field_index: Optional[int] = None
        self.message_content: Optional[str] = None
        self.create_thread: bool = False
        self.thread_name: Optional[str] = None

        # Кнопки для публикации
        self.custom_buttons: List[Dict[str, Any]] = []

        # Embed по умолчанию
        self.embed = discord.Embed(
            title=DEFAULT_EMBED_TITLE,
            description=DEFAULT_EMBED_DESCRIPTION,
            color=discord.Color.blurple()
        )

        # Добавляем выбор цвета
        self.add_item(self.ColorSelect())

    class ColorSelect(ui.Select):
        """Выпадающий список для выбора готового цвета."""

        def __init__(self):
            options = [
                discord.SelectOption(label=name, value=name, emoji="🎨")
                for name in PRESET_COLORS.keys()
            ]
            super().__init__(
                placeholder="🎨 Выбрать готовый цвет...",
                min_values=1,
                max_values=1,
                options=options,
                row=1
            )

        async def callback(self, interaction: discord.Interaction):
            view: GigaBuilderView = self.view
            color_name = self.values[0]
            view.embed.color = PRESET_COLORS[color_name]
            await interaction.response.defer()
            await view.update_preview()

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: ui.Item
    ) -> None:
        logger.error(f"Ошибка в GigaBuilderView: {error}", exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Произошла непредвиденная ошибка: {error}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Произошла непредвиденная ошибка: {error}",
                    ephemeral=True
                )
        except (discord.NotFound, discord.InteractionResponded):
            logger.error("Не удалось отправить сообщение об ошибке пользователю.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверка что только автор может редактировать."""
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Это не ваш конструктор!",
                ephemeral=True,
                delete_after=5
            )
            return False
        return True

    async def update_preview(self):
        """Обновляет предпросмотр embed."""
        if self.message:
            try:
                # Убираем старые FieldSelect из view
                for item in list(self.children):
                    if isinstance(item, FieldSelect):
                        self.remove_item(item)

                await self.message.edit(embed=self.embed, view=self)
            except discord.NotFound:
                logger.warning("Сообщение для обновления не найдено")
                self.stop()

    # ===================================================================
    # ROW 0: Основные настройки
    # ===================================================================

    @ui.button(label="📝 Основное", style=discord.ButtonStyle.primary, row=0)
    async def main_settings_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MainSettingsModal(self))

    @ui.button(label="✍️ Автор", style=discord.ButtonStyle.secondary, row=0)
    async def author_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AuthorModal(self))

    @ui.button(label="🦶 Футер", style=discord.ButtonStyle.secondary, row=0)
    async def footer_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(FooterModal(self))

    @ui.button(label="💬 Текст", style=discord.ButtonStyle.secondary, row=0)
    async def content_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ContentModal(self))

    @ui.button(label="📊 Статус", style=discord.ButtonStyle.secondary, row=0)
    async def stats_button(self, interaction: discord.Interaction, button: ui.Button):
        """Показывает статистику использования лимитов."""
        stats = get_embed_stats(self.embed)
        warnings = get_warnings(self.embed)
        is_valid, errors = validate_embed(self.embed)

        status_text = "**📊 Статус Embed**\n\n"
        status_text += f"📌 Заголовок: `{stats['title']}`\n"
        status_text += f"📝 Описание: `{stats['description']}`\n"
        status_text += f"✍️ Автор: `{stats['author']}`\n"
        status_text += f"🦶 Футер: `{stats['footer']}`\n"
        status_text += f"📋 Полей: `{stats['fields']}`\n"
        status_text += f"📊 **Всего символов: `{stats['total']}`**\n"

        if warnings:
            status_text += "\n**⚠️ Предупреждения:**\n"
            status_text += "\n".join(warnings)

        if not is_valid:
            status_text += "\n\n**❌ Ошибки:**\n"
            status_text += "\n".join(errors)

        await interaction.response.send_message(status_text, ephemeral=True)

    # ===================================================================
    # ROW 2: Изображения и кнопки
    # ===================================================================

    @ui.button(label="🖼️ Изображение", style=discord.ButtonStyle.secondary, row=2)
    async def image_button(self, interaction: discord.Interaction, button: ui.Button):
        view = ImageActionView(self, image_type='image')
        await interaction.response.send_message(
            "Выберите источник изображения:",
            view=view,
            ephemeral=True
        )

    @ui.button(label="📌 Превью", style=discord.ButtonStyle.secondary, row=2)
    async def thumbnail_button(self, interaction: discord.Interaction, button: ui.Button):
        view = ImageActionView(self, image_type='thumbnail')
        await interaction.response.send_message(
            "Выберите источник миниатюры:",
            view=view,
            ephemeral=True
        )

    @ui.button(label="🔘 Кнопки", style=discord.ButtonStyle.secondary, row=2)
    async def buttons_builder(self, interaction: discord.Interaction, button: ui.Button):
        # Импортируем здесь чтобы избежать циклических импортов
        from .button_builder import ButtonBuilderView
        view = ButtonBuilderView(self)
        await interaction.response.send_message(
            "**Конструктор кнопок**\n"
            f"Добавлено кнопок: {len(self.custom_buttons)}/25",
            view=view,
            ephemeral=True
        )

    # ===================================================================
    # ROW 3: Управление полями
    # ===================================================================

    @ui.button(label="[+] Добавить поле", style=discord.ButtonStyle.success, row=3)
    async def add_field_button(self, interaction: discord.Interaction, button: ui.Button):
        if len(self.embed.fields) >= FIELDS_MAX:
            return await interaction.response.send_message(
                f"❌ Достигнут лимит в {FIELDS_MAX} полей!",
                ephemeral=True
            )
        await interaction.response.send_modal(FieldModal(self))

    @ui.button(label="✏️ Изменить/Удалить поле", style=discord.ButtonStyle.primary, row=3)
    async def edit_delete_field_button(self, interaction: discord.Interaction, button: ui.Button):
        if not self.embed.fields:
            return await interaction.response.send_message(
                "Нет полей для редактирования или удаления.",
                ephemeral=True
            )

        edit_view = ui.View(timeout=180)
        edit_view.add_item(FieldSelect(self))
        await interaction.response.send_message(
            "Выберите поле:",
            view=edit_view,
            ephemeral=True
        )

    @ui.button(label="⇅ Порядок полей", style=discord.ButtonStyle.secondary, row=3)
    async def reorder_fields_button(self, interaction: discord.Interaction, button: ui.Button):
        if len(self.embed.fields) < 2:
            return await interaction.response.send_message(
                "Нужно как минимум 2 поля для изменения их порядка.",
                ephemeral=True
            )
        await interaction.response.send_message(
            "Выберите, какое поле и куда переместить:",
            view=ReorderFieldsView(self),
            ephemeral=True
        )

    @ui.button(label="➖ Разделитель", style=discord.ButtonStyle.secondary, row=3)
    async def add_separator_button(self, interaction: discord.Interaction, button: ui.Button):
        if len(self.embed.fields) >= FIELDS_MAX:
            return await interaction.response.send_message(
                f"❌ Достигнут лимит в {FIELDS_MAX} полей!",
                ephemeral=True
            )
        self.embed.add_field(name="\u200b", value="\u200b", inline=False)
        await interaction.response.defer()
        await self.update_preview()

    # ===================================================================
    # ROW 4: Шаблоны, планирование, публикация
    # ===================================================================

    @ui.button(label="📋 Шаблоны", style=discord.ButtonStyle.secondary, row=4)
    async def templates_button(self, interaction: discord.Interaction, button: ui.Button):
        from .template_views import TemplateActionView
        view = TemplateActionView(self)
        await interaction.response.send_message(
            "**📋 Шаблоны**\nВыберите действие:",
            view=view,
            ephemeral=True
        )

    @ui.button(label="⏰ Запланировать", style=discord.ButtonStyle.secondary, row=4)
    async def schedule_button(self, interaction: discord.Interaction, button: ui.Button):
        from ..modals.schedule_modal import ScheduleModal
        await interaction.response.send_modal(ScheduleModal(self))

    @ui.button(label="🧵 +Тред", style=discord.ButtonStyle.secondary, row=4)
    async def thread_toggle_button(self, interaction: discord.Interaction, button: ui.Button):
        self.create_thread = not self.create_thread

        if self.create_thread:
            # Запрашиваем название треда
            from ..modals.thread_modal import ThreadNameModal
            await interaction.response.send_modal(ThreadNameModal(self))
        else:
            self.thread_name = None
            await interaction.response.send_message(
                "🧵 Создание треда **отключено**.",
                ephemeral=True,
                delete_after=5
            )

    @ui.button(label="✅ Опубликовать", style=discord.ButtonStyle.success, row=4)
    async def publish_button(self, interaction: discord.Interaction, button: ui.Button):
        # Валидация
        is_valid, errors = validate_embed(self.embed)
        if not is_valid:
            return await interaction.response.send_message(
                "❌ **Ошибки валидации:**\n" + "\n".join(errors),
                ephemeral=True
            )

        # Подготовка embed
        final_embed = self.embed.copy()

        # Парсинг цветного текста
        if final_embed.description:
            final_embed.description = parse_text_colors(final_embed.description)
        for idx, field in enumerate(final_embed.fields):
            final_embed.set_field_at(
                idx,
                name=field.name,
                value=parse_text_colors(field.value),
                inline=field.inline
            )

        # Подготовка контента
        content = self.message_content or ""
        mention_text = self.role_to_mention.mention if self.role_to_mention else ""
        final_content = f"{mention_text} {content}".strip() or None

        # Подготовка кнопок
        view = None
        if self.custom_buttons:
            from .button_builder import create_button_view
            view = create_button_view(self.custom_buttons, self.client)

        # Публикация
        try:
            published_message = await self.target_channel.send(
                content=final_content,
                embed=final_embed,
                view=view
            )

            # Создание треда если включено
            if self.create_thread and self.thread_name:
                await published_message.create_thread(
                    name=self.thread_name,
                    auto_archive_duration=1440  # 24 часа
                )
                logger.info(f"Thread created: {self.thread_name}")

        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ Нет прав для отправки сообщений в этот канал.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка публикации: {e}", exc_info=True)
            return await interaction.response.send_message(
                f"❌ Ошибка публикации: {e}",
                ephemeral=True
            )

        # Закрываем конструктор
        self.clear_items()
        thread_info = f"\n🧵 Тред создан: **{self.thread_name}**" if self.create_thread else ""
        await interaction.response.edit_message(
            content=f"✅ **Анонс успешно опубликован!**{thread_info}",
            view=None,
            embed=None
        )
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.danger, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        self.clear_items()
        await interaction.response.edit_message(
            content="❌ Конструктор закрыт.",
            view=None,
            embed=None
        )
        self.stop()
