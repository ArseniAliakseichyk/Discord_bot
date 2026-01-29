"""
Модальное окно для настройки изображений по URL.
"""
import discord
from discord import ui
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..views.main_view import GigaBuilderView


class ImageModal(ui.Modal, title="Настройка изображения по URL"):
    """Модальное окно для ввода URL изображения."""

    def __init__(self, view: 'GigaBuilderView', image_type: str):
        super().__init__()
        self.view = view
        self.image_type = image_type  # 'image' или 'thumbnail'

        # Заполняем текущим URL
        if image_type == 'image' and view.embed.image:
            self.url.default = view.embed.image.url
        elif image_type == 'thumbnail' and view.embed.thumbnail:
            self.url.default = view.embed.thumbnail.url

    url = ui.TextInput(
        label="URL изображения",
        required=False,
        placeholder="https://example.com/image.png"
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip() if self.url.value else None

        if self.image_type == 'image':
            self.view.embed.set_image(url=url)
        else:
            self.view.embed.set_thumbnail(url=url)

        await interaction.response.defer()
        await self.view.update_preview()
