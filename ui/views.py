"""Shared view behaviour: disabling components and handling timeouts/errors."""

from __future__ import annotations

import contextlib
import logging

import discord
from discord import ui

logger = logging.getLogger("bot.views")


def disable_all(view: ui.View) -> None:
    """Grey out every interactive component (used on send, cancel and timeout)."""
    for item in view.children:
        if isinstance(item, (ui.Button, ui.Select)):
            item.disabled = True


class EphemeralView(ui.View):
    """View delivered as an ephemeral response.

    An ephemeral message has no ``Message`` object to hold on to, so the view
    remembers the interaction that produced it. Without that, ``on_timeout`` has
    no way to grey out the buttons and they keep looking clickable while every
    click fails with "This interaction failed".
    """

    def __init__(self, *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self._origin: discord.Interaction | None = None

    def bind(self, interaction: discord.Interaction) -> None:
        """Remember the interaction whose response carries this view."""
        self._origin = interaction

    async def on_timeout(self) -> None:
        disable_all(self)
        if self._origin is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await self._origin.edit_original_response(view=self)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: ui.Item,
    ) -> None:
        logger.error("%s failed on %r", type(self).__name__, item, exc_info=error)
        message = "⚠️ Произошла внутренняя ошибка."
        with contextlib.suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
