"""
Views для управления изображениями.
"""
import discord
from discord import ui
import asyncio
import os
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_view import GigaBuilderView

from ..modals.image_modals import ImageModal
from ..constants import MODAL_WAIT_TIMEOUT

logger = logging.getLogger(__name__)


class ImageActionView(ui.View):
    """View для выбора источника изображения (файл или URL)."""

    def __init__(self, builder_view: 'GigaBuilderView', image_type: str):
        super().__init__(timeout=180)
        self.builder_view = builder_view
        self.image_type = image_type  # 'image' или 'thumbnail'

    @ui.button(label="Загрузить файл", style=discord.ButtonStyle.success, emoji="🖥️")
    async def upload_file(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            pass

        image_name = 'изображение' if self.image_type == 'image' else 'миниатюру'
        prompt_message = (
            f"**Пожалуйста, отправьте {image_name} "
            f"(картинку или .gif) в этот канал в течение {MODAL_WAIT_TIMEOUT} секунд.**"
        )

        prompt_message_obj = await interaction.followup.send(prompt_message, ephemeral=True)

        def check(m: discord.Message):
            return (
                m.author == interaction.user and
                m.channel == interaction.channel and
                m.attachments
            )

        try:
            msg = await self.builder_view.client.wait_for(
                "message",
                timeout=float(MODAL_WAIT_TIMEOUT),
                check=check
            )
        except asyncio.TimeoutError:
            try:
                await prompt_message_obj.delete()
            except discord.NotFound:
                pass
            await interaction.followup.send(
                "⏰ Время вышло. Попробуйте еще раз.",
                ephemeral=True
            )
            return

        attachment = msg.attachments[0]
        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            await interaction.followup.send(
                "❌ Прикрепленный файл не является изображением.",
                ephemeral=True
            )
            await self._cleanup_messages(msg, prompt_message_obj)
            return

        # Получаем лог-канал для хостинга изображения
        LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
        if not LOG_CHANNEL_ID:
            await interaction.followup.send(
                "❌ Переменная окружения LOG_CHANNEL_ID не найдена.",
                ephemeral=True
            )
            await self._cleanup_messages(msg, prompt_message_obj)
            return

        try:
            log_channel = await self.builder_view.client.fetch_channel(int(LOG_CHANNEL_ID))
        except (ValueError, discord.NotFound):
            await interaction.followup.send(
                "❌ Лог-канал не найден. Проверьте LOG_CHANNEL_ID в .env файле.",
                ephemeral=True
            )
            await self._cleanup_messages(msg, prompt_message_obj)
            return

        try:
            log_message = await log_channel.send(file=await attachment.to_file())
            new_image_url = log_message.attachments[0].url

            if self.image_type == 'image':
                self.builder_view.embed.set_image(url=new_image_url)
            else:
                self.builder_view.embed.set_thumbnail(url=new_image_url)

            logger.info(f"Image uploaded: {new_image_url}")

        except Exception as e:
            logger.error(f"Ошибка при пересылке изображения в лог-канал: {e}")
            await interaction.followup.send(
                "❌ Произошла ошибка при обработке изображения.",
                ephemeral=True
            )
            await self._cleanup_messages(msg, prompt_message_obj)
            return

        await self.builder_view.update_preview()
        await self._cleanup_messages(msg, prompt_message_obj)
        self.stop()

    @ui.button(label="Вставить URL", style=discord.ButtonStyle.primary, emoji="🔗")
    async def use_url(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ImageModal(self.builder_view, self.image_type))
        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            pass
        self.stop()

    @ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_image(self, interaction: discord.Interaction, button: ui.Button):
        if self.image_type == 'image':
            self.builder_view.embed.set_image(url=None)
        else:
            self.builder_view.embed.set_thumbnail(url=None)

        await interaction.response.send_message(
            "✅ Изображение удалено.",
            ephemeral=True,
            delete_after=3
        )
        await self.builder_view.update_preview()
        self.stop()

    async def _cleanup_messages(self, msg: discord.Message, prompt: discord.InteractionMessage):
        """Очистка временных сообщений."""
        try:
            await msg.delete()
        except discord.NotFound:
            pass

        try:
            await prompt.delete()
        except discord.NotFound:
            pass
