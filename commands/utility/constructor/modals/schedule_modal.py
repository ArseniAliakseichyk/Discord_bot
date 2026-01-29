"""
Модальное окно для планирования публикации.
"""
import discord
from discord import ui
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView

from ..utils.scheduler import schedule_message
from ..utils.validators import validate_embed
from ..utils.colors import parse_text_colors

logger = logging.getLogger(__name__)


class ScheduleModal(ui.Modal, title="Запланировать публикацию"):
    """Модальное окно для выбора времени публикации."""

    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view

        # Устанавливаем дефолт на +1 час
        default_time = datetime.now() + timedelta(hours=1)
        self.date_input.default = default_time.strftime("%d.%m.%Y")
        self.time_input.default = default_time.strftime("%H:%M")

    date_input = ui.TextInput(
        label="Дата (ДД.ММ.ГГГГ)",
        placeholder="25.12.2024",
        max_length=10,
        required=True
    )

    time_input = ui.TextInput(
        label="Время (ЧЧ:ММ)",
        placeholder="15:30",
        max_length=5,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Парсим дату и время
        try:
            date_str = self.date_input.value.strip()
            time_str = self.time_input.value.strip()

            # Поддержка разных форматов
            for date_fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    date_part = datetime.strptime(date_str, date_fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Неверный формат даты")

            for time_fmt in ["%H:%M", "%H.%M"]:
                try:
                    time_part = datetime.strptime(time_str, time_fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Неверный формат времени")

            publish_at = datetime.combine(date_part.date(), time_part.time())

        except ValueError as e:
            return await interaction.response.send_message(
                f"❌ Ошибка формата: {e}\n"
                "Используйте: дата `ДД.ММ.ГГГГ`, время `ЧЧ:ММ`",
                ephemeral=True
            )

        # Проверяем что время в будущем
        if publish_at <= datetime.now():
            return await interaction.response.send_message(
                "❌ Время публикации должно быть в будущем!",
                ephemeral=True
            )

        # Валидация embed
        is_valid, errors = validate_embed(self.view.embed)
        if not is_valid:
            return await interaction.response.send_message(
                "❌ **Ошибки валидации:**\n" + "\n".join(errors),
                ephemeral=True
            )

        # Подготовка embed (парсинг цветов)
        final_embed = self.view.embed.copy()
        if final_embed.description:
            final_embed.description = parse_text_colors(final_embed.description)
        for idx, field in enumerate(final_embed.fields):
            final_embed.set_field_at(
                idx,
                name=field.name,
                value=parse_text_colors(field.value),
                inline=field.inline
            )

        # Планируем публикацию
        try:
            task_id = await schedule_message(
                client=self.view.client,
                channel=self.view.target_channel,
                embed=final_embed,
                publish_at=publish_at,
                author_id=self.view.author.id,
                message_content=self.view.message_content,
                buttons=self.view.custom_buttons,
                create_thread=self.view.create_thread,
                thread_name=self.view.thread_name,
                role_to_mention=self.view.role_to_mention
            )

            # Форматируем время для отображения
            formatted_time = publish_at.strftime("%d.%m.%Y в %H:%M")

            await interaction.response.send_message(
                f"✅ **Публикация запланирована!**\n"
                f"📅 Дата: **{formatted_time}**\n"
                f"📍 Канал: {self.view.target_channel.mention}\n"
                f"🔑 ID задачи: `{task_id}`\n\n"
                f"*Для отмены используйте `/schedule_cancel {task_id}`*",
                ephemeral=True
            )

            logger.info(
                f"Message scheduled by {interaction.user} for {publish_at} "
                f"in {self.view.target_channel.name}"
            )

        except Exception as e:
            logger.error(f"Failed to schedule message: {e}", exc_info=True)
            await interaction.response.send_message(
                f"❌ Ошибка планирования: {e}",
                ephemeral=True
            )
