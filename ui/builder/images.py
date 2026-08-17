"""Choosing an image for the embed: upload a file, or paste a URL.

Uploads are re-hosted by posting the attachment to the configured log channel
and reusing Discord's own CDN link, because an embed needs a stable URL.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord import ui

from core.constants import IMAGE_ACTION_TIMEOUT
from ui.builder.modals import ImageModal
from ui.v2 import PanelView, make_panel

if TYPE_CHECKING:
    from ui.builder.panel import GigaBuilderView

logger = logging.getLogger("bot.builder")

UPLOAD_WAIT = 60.0


async def _quiet_delete(message: discord.Message | None) -> None:
    """Delete a message, ignoring the permissions the bot may not have.

    Removing the user's own upload needs Manage Messages; without this guard a
    missing permission escalated into a traceback in the middle of a successful
    flow.
    """
    if message is None:
        return
    with contextlib.suppress(discord.HTTPException):
        await message.delete()


class ImageSourceRow(ui.ActionRow["ImageActionView"]):
    @ui.button(label="Загрузить файл", emoji="🖥️", style=discord.ButtonStyle.success)
    async def upload(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.upload_flow(interaction)

    @ui.button(label="Вставить URL", emoji="🔗", style=discord.ButtonStyle.primary)
    async def by_url(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        # No delete_original_response() here: send_modal() leaves no original
        # response to delete, so that call always raised NotFound.
        await interaction.response.send_modal(ImageModal(view.builder, view.kind))
        view.stop()


class ImageActionView(PanelView):
    def __init__(self, builder: GigaBuilderView, kind: str) -> None:
        super().__init__(timeout=IMAGE_ACTION_TIMEOUT)
        self.builder = builder
        self.kind = kind
        what = "изображения" if kind == "image" else "миниатюры"
        self.add_item(make_panel(body=f"Выберите источник {what}:"))
        self.add_item(ImageSourceRow())

    async def upload_flow(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        with contextlib.suppress(discord.HTTPException):
            await interaction.delete_original_response()

        what = "изображение" if self.kind == "image" else "миниатюру"
        prompt = await interaction.followup.send(
            view=make_prompt(
                f"**Отправьте {what} (картинку или .gif) в этот канал "
                f"в течение {int(UPLOAD_WAIT)} секунд.**"
            ),
            ephemeral=True,
            wait=True,
        )

        def check(message: discord.Message) -> bool:
            return (
                message.author == interaction.user
                and message.channel == interaction.channel
                and bool(message.attachments)
            )

        upload: discord.Message | None = None
        try:
            upload = await self.builder.bot.wait_for(
                "message", timeout=UPLOAD_WAIT, check=check
            )
            attachment = upload.attachments[0]
            if not attachment.content_type or not attachment.content_type.startswith(
                "image/"
            ):
                await self._say(interaction, "❌ Прикреплённый файл не является изображением.")
                return

            log_channel_id = self.builder.bot.settings.log_channel_id
            if not log_channel_id:
                await self._say(
                    interaction,
                    "❌ LOG_CHANNEL_ID не настроен — загрузка файлов недоступна. "
                    "Используйте «Вставить URL».",
                )
                return

            channel = self.builder.bot.get_channel(log_channel_id)
            if channel is None:
                channel = await self.builder.bot.fetch_channel(log_channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                await self._say(interaction, "❌ LOG_CHANNEL_ID указывает не на канал.")
                return

            stored = await channel.send(file=await attachment.to_file())
            self.builder.state.set_media(self.kind, stored.attachments[0].url)
        except TimeoutError:
            await self._say(interaction, "⏰ Время вышло.")
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to store the uploaded image")
            await self._say(interaction, "❌ Не удалось обработать изображение.")
            return
        finally:
            # Always tidy up, including on the error paths — previously each
            # branch repeated these two calls and one of them was missed.
            await _quiet_delete(upload)
            await _quiet_delete(prompt)

        await self.builder.update_preview()
        self.stop()

    @staticmethod
    async def _say(interaction: discord.Interaction, text: str) -> None:
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(view=make_prompt(text), ephemeral=True)


def make_prompt(text: str) -> ui.LayoutView:
    view = PanelView(timeout=None)
    view.add_item(make_panel(body=text))
    return view
