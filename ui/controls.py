"""Now-playing panel and playback controls (Components V2, wavelink-backed).

The panel replaces the old embed: a ``Container`` holds the track title in a
``Section`` next to the artwork thumbnail, then the metadata lines, then the
button row. Because a v2 message carries no ``content`` or ``embeds``, this view
is the whole message.
"""

from __future__ import annotations

import logging
import time
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


def _time_line(track: wavelink.Playable, player: wavelink.Player) -> str:
    """The track's length, plus when it ends.

    The end time is a Discord relative timestamp, which the *client* renders
    and counts down on its own. A rendered "01:01 / 03:35" is frozen the moment
    it is sent and is wrong a second later, and keeping it truthful would mean
    editing the message every few seconds for every guild - which is why mature
    players show the length only. This gets a live readout for free.

    While paused there is no meaningful end time, so the position is shown as
    the static value it genuinely is.
    """
    if track.is_stream:
        return "**Длительность:** 🔴 LIVE"
    if not track.length:
        return ""
    total = format_ms(track.length)
    if player.paused:
        return f"**Длительность:** {total}\n-# На паузе на {format_ms(player.position)}"
    ends_at = int(time.time() + max(0, track.length - player.position) / 1000)
    return f"**Длительность:** {total}\n-# Закончится <t:{ends_at}:R>"


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
    """Play/pause, skip and stop, gated on the DJ role."""

    def __init__(self, *, paused: bool = False) -> None:
        super().__init__()
        # The control advertises what pressing it will do.
        self.play_pause.label = "Продолжить" if paused else "Пауза"
        self.play_pause.emoji = "▶️" if paused else "⏸️"

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
    async def play_pause(self, interaction: discord.Interaction, _: ui.Button) -> None:
        """One button for both states.

        Two buttons meant one of them was always dead: whichever did not match
        the current state simply told the user off. This mirrors what every
        player does - the control shows the action it will perform.
        """
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        view = self.view
        assert view is not None
        player = player_of(interaction.guild)
        if player is None or player.current is None:
            await self._notify(interaction, MSG_NOTHING_PLAYING)
            return
        await player.pause(not player.paused)
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
    @ui.button(label="Стоп", emoji="⏹️", style=discord.ButtonStyle.secondary)
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
        time_line = _time_line(track, player)
        if time_line:
            details.append(time_line)
        if not player.queue.is_empty:
            details.append(f"**Далее в очереди:** {len(player.queue)}")

        requester = _requester(track)
        if requester:
            details.append(f"-# Добавлено: {requester}")

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay("\n".join(details)))
        container.add_item(ui.Separator())
        container.add_item(PlaybackControls(paused=player.paused))
        self.add_item(container)
