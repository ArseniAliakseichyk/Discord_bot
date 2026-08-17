"""Now-playing panel and playback controls (Components V2, wavelink-backed).

The panel replaces the old embed: a ``Container`` holds the track title in a
``Section`` next to the artwork thumbnail, then the metadata lines, then the
button row. Because a v2 message carries no ``content`` or ``embeds``, this view
is the whole message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
import wavelink
from discord import ui

from core.constants import (
    MSG_BOT_NOT_CONNECTED,
    MSG_NEED_DJ,
    MSG_NOTHING_PLAYING,
    SPOTIFY_COLOR,
)
from ui.v2 import PanelView, make_panel
from utils.checks import user_is_dj
from utils.formatting import format_ms
from utils.player import player_of

if TYPE_CHECKING:
    from cogs.music import Music

logger = logging.getLogger("bot.controls")

_SOURCE_NAMES = {
    "youtube": "YouTube",
    "youtubemusic": "YouTube Music",
    "soundcloud": "SoundCloud",
    "spotify": "Spotify",
    "applemusic": "Apple Music",
    "deezer": "Deezer",
    "bandcamp": "Bandcamp",
    "twitch": "Twitch",
    "vimeo": "Vimeo",
    "local": "Локальный файл",
    "http": "Прямая ссылка",
}

_SOURCE_COLORS = {
    "spotify": SPOTIFY_COLOR,
    "local": 0x57F287,
    "soundcloud": 0xFF5500,
}
_DEFAULT_SOURCE_COLOR = 0xFFD966

#: Width of the textual progress bar, in characters.
PROGRESS_WIDTH = 18


def _requester(track: wavelink.Playable) -> str | None:
    """Display name of whoever queued the track, if it was recorded.

    Only the name is needed now: a v2 panel has no footer-icon slot, so the
    stored avatar URL is used solely for restoring sessions (see cogs.music).
    """
    extras = getattr(track, "extras", None)
    if extras is None:
        return None
    name = getattr(extras, "requester", None)
    return str(name) if name else None


def _progress_bar(position: int, length: int) -> str:
    """Render ``▬▬🔘▬▬`` for the current position within the track."""
    if length <= 0:
        return ""
    filled = max(0, min(PROGRESS_WIDTH - 1, position * PROGRESS_WIDTH // length))
    return "▬" * filled + "🔘" + "▬" * (PROGRESS_WIDTH - 1 - filled)


def _status_line(player: wavelink.Player) -> str:
    if player.paused:
        return "⏸️ На паузе"
    if player.queue.mode is wavelink.QueueMode.loop:
        return "🔂 Повтор трека"
    if player.queue.mode is wavelink.QueueMode.loop_all:
        return "🔁 Повтор очереди"
    if player.autoplay == wavelink.AutoPlayMode.enabled:
        return "📻 Автоплей"
    return "▶️ Воспроизведение"


def now_playing_panel(
    track: wavelink.Playable, player: wavelink.Player, cog: Music
) -> NowPlayingView:
    """Build the complete now-playing message for ``track``."""
    return NowPlayingView(cog, track=track, player=player)


class PlaybackControls(ui.ActionRow["NowPlayingView"]):
    """Pause / resume / skip / stop, gated on the DJ role."""

    async def _guard(self, interaction: discord.Interaction) -> bool:
        view = self.view
        if (
            view is None
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return False
        if await user_is_dj(view.cog.bot, interaction.user):
            return True
        await interaction.response.send_message(MSG_NEED_DJ, ephemeral=True)
        return False

    @staticmethod
    async def _notify(interaction: discord.Interaction, message: str) -> None:
        """Tell the user why a button did nothing (the interaction is deferred)."""
        try:
            await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Could not send button feedback", exc_info=True)

    @ui.button(label="Пауза", emoji="⏸️", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        view = self.view
        assert view is not None
        player = player_of(interaction.guild)
        if player is None:
            await self._notify(interaction, MSG_BOT_NOT_CONNECTED)
        elif not player.playing or player.paused:
            await self._notify(interaction, "❌ Нечего ставить на паузу.")
        else:
            await player.pause(True)
            await view.cog.refresh_now_message(player)

    @ui.button(label="Продолжить", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        view = self.view
        assert view is not None
        player = player_of(interaction.guild)
        if player is None:
            await self._notify(interaction, MSG_BOT_NOT_CONNECTED)
        elif not player.paused:
            await self._notify(interaction, "❌ Воспроизведение не на паузе.")
        else:
            await player.pause(False)
            await view.cog.refresh_now_message(player)

    @ui.button(label="Скип", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        player = player_of(interaction.guild)
        if player is None or not (player.playing or player.current):
            await self._notify(interaction, MSG_NOTHING_PLAYING)
        else:
            await player.skip(force=True)

    # NOT named `stop`: on a View that shadows View.stop(); kept distinct here
    # too so the two classes stay symmetrical.
    @ui.button(label="Стоп", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_playback(
        self, interaction: discord.Interaction, _: ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        view = self.view
        assert view is not None
        player = player_of(interaction.guild)
        if player is None:
            await self._notify(interaction, MSG_BOT_NOT_CONNECTED)
        else:
            await view.cog.stop_player(player)


class NowPlayingView(PanelView):
    """The now-playing message: track card plus playback controls."""

    def __init__(
        self,
        cog: Music,
        *,
        track: wavelink.Playable | None = None,
        player: wavelink.Player | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        if track is None or player is None:
            # Template instance used only to register the persistent custom_ids.
            container = make_panel(title="🎵 Сейчас играет")
            container.add_item(ui.Separator())
            container.add_item(PlaybackControls())
            self.add_item(container)
            return

        source = (track.source or "").lower()
        accent = _SOURCE_COLORS.get(source, _DEFAULT_SOURCE_COLOR)
        title = f"[{track.title}]({track.uri})" if track.uri else f"**{track.title}**"

        header = f"### 🎵 Сейчас играет\n{title}"
        if track.author:
            header += f"\n-# {track.author}"

        if track.artwork:
            container = make_panel(accent=accent)
            container.add_item(
                ui.Section(ui.TextDisplay(header), accessory=ui.Thumbnail(track.artwork))
            )
        else:
            container = make_panel(body=header, accent=accent)

        details = [
            f"**Источник:** {_SOURCE_NAMES.get(source, source.title() or 'YouTube')}",
            f"**Статус:** {_status_line(player)}",
        ]
        if track.is_stream:
            details.append("**Длительность:** 🔴 LIVE")
        elif track.length:
            details.append(
                f"**Длительность:** {format_ms(track.length)}\n"
                f"{_progress_bar(player.position, track.length)}\n"
                f"-# {format_ms(player.position)} / {format_ms(track.length)}"
            )
        if not player.queue.is_empty:
            details.append(f"**Далее в очереди:** {len(player.queue)}")

        requester = _requester(track)
        if requester:
            details.append(f"-# Добавлено: {requester}")

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay("\n".join(details)))
        container.add_item(ui.Separator())
        container.add_item(PlaybackControls())
        self.add_item(container)
