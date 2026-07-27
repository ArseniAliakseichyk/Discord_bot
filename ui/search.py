"""Select menu for choosing among top search results."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import wavelink

from core.constants import MSG_JOIN_VOICE_FIRST, SEARCH_TIMEOUT, SELECT_LABEL_LIMIT
from utils.formatting import format_ms

if TYPE_CHECKING:
    from cogs.music import Music


class SearchSelect(discord.ui.Select):
    def __init__(self, tracks: list[wavelink.Playable]) -> None:
        self.tracks = tracks
        options: list[discord.SelectOption] = []
        for i, track in enumerate(tracks):
            duration = "LIVE" if track.is_stream else format_ms(track.length)
            description = f"{track.author} • {duration}" if track.author else duration
            options.append(
                discord.SelectOption(
                    label=track.title[:SELECT_LABEL_LIMIT],
                    value=str(i),
                    description=description[:SELECT_LABEL_LIMIT],
                )
            )
        super().__init__(
            placeholder="Выберите трек...", min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SearchView = self.view  # type: ignore[assignment]
        track = self.tracks[int(self.values[0])]
        await interaction.response.defer()
        # add_and_play returns False when the requester is no longer in a voice
        # channel — don't claim success in that case.
        queued = await view.cog.add_and_play(interaction, track, view.requester)
        content = (
            f"✅ Добавлено: **{track.title}**" if queued else MSG_JOIN_VOICE_FIRST
        )
        if view.message is not None:
            try:
                await view.message.edit(content=content, view=None)
            except discord.HTTPException:
                pass
        view.stop()


class SearchView(discord.ui.View):
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
        self.add_item(SearchSelect(tracks))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester.id:
            await interaction.response.send_message(
                "Это не ваш поиск.", ephemeral=True, delete_after=5
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content="⏰ Время выбора истекло.", view=None)
            except discord.HTTPException:
                pass
