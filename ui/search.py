"""Select menu for choosing among top search results (Components V2).

A v2 message carries no ``content``, so the prompt, the results and the final
confirmation all live inside the view and the whole view is swapped on each
state change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import wavelink
from discord import ui

from core.constants import MSG_JOIN_VOICE_FIRST, SEARCH_TIMEOUT, SELECT_LABEL_LIMIT
from ui.v2 import PanelView, as_select, make_panel
from utils.formatting import format_ms

if TYPE_CHECKING:
    from cogs.music import Music


class SearchRow(ui.ActionRow["SearchView"]):
    def __init__(self, tracks: list[wavelink.Playable]) -> None:
        super().__init__()
        self.tracks = tracks
        as_select(self.choose).options = [
            discord.SelectOption(
                label=track.title[:SELECT_LABEL_LIMIT],
                value=str(index),
                description=(
                    f"{track.author} • {'LIVE' if track.is_stream else format_ms(track.length)}"
                    if track.author
                    else ("LIVE" if track.is_stream else format_ms(track.length))
                )[:SELECT_LABEL_LIMIT],
            )
            for index, track in enumerate(tracks)
        ]

    @ui.select(placeholder="Выберите трек…", min_values=1, max_values=1, options=[])
    async def choose(self, interaction: discord.Interaction, select: ui.Select) -> None:
        view = self.view
        assert view is not None
        track = self.tracks[int(select.values[0])]
        await interaction.response.defer()
        # add_and_play returns False when the requester is no longer in a voice
        # channel — don't claim success in that case.
        queued = await view.cog.add_and_play(interaction, track, view.requester)
        text = f"✅ Добавлено: **{track.title}**" if queued else MSG_JOIN_VOICE_FIRST
        await view.finish(text)


class SearchView(PanelView):
    def __init__(
        self,
        cog: Music,
        tracks: list[wavelink.Playable],
        requester: discord.Member,
    ) -> None:
        super().__init__(timeout=SEARCH_TIMEOUT)
        self.cog = cog
        self.requester = requester
        self.message: discord.Message | None = None
        container = make_panel(title="🔎 Результаты поиска")
        container.add_item(ui.Separator())
        container.add_item(SearchRow(tracks))
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester.id:
            await interaction.response.send_message(
                "Это не ваш поиск.", ephemeral=True, delete_after=5
            )
            return False
        return True

    async def finish(self, text: str) -> None:
        """Replace the menu with a final one-line result and stop listening."""
        self.clear_items()
        self.add_item(make_panel(body=text))
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    async def on_timeout(self) -> None:
        await self.finish("⏰ Время выбора истекло.")
