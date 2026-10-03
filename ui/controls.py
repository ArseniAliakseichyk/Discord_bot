"""Now-playing panel and playback controls (Components V2, wavelink-backed).

One message per guild shows everything about playback: the track, its state,
what plays next and who did what last. Commands and buttons change the player
and then redraw this panel, so the channel is not filled with "Paused." and
"Skipped." confirmations - the panel *is* the confirmation.

The layout follows what established players settled on (compare Vocard's
controller): a transport row, a modes row, and a list to jump ahead in the
queue. When nothing is playing the panel is not deleted but turns idle, so the
channel keeps one tidy record instead of a trail of "queue ended" messages.

All decisions live in the Music cog; this module only draws and dispatches.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord
import wavelink
from discord import ui
from discord.utils import escape_markdown

from core.constants import MSG_BOT_NOT_CONNECTED, MSG_NEED_DJ, MSG_NOTHING_PLAYING, SPOTIFY_COLOR
from ui.v2 import PanelView, as_select, make_panel
from utils.checks import bot_voice_refusal, user_is_dj
from utils.formatting import format_ms
from utils.player import is_live, player_of
from utils.radio import is_radio_pick

if TYPE_CHECKING:
    from cogs.music import Music

logger = logging.getLogger("bot.controls")

# Fixed ids, so a panel posted before a restart still works after it: the cog
# registers a template view with bot.add_view(). Without them discord.py made
# up random ids per message, and every button on an older panel answered
# "This interaction failed". Changing one orphans every panel already posted.
CID_BACK = "np:back"
CID_PLAY_PAUSE = "np:play_pause"
CID_SKIP = "np:skip"
CID_STOP = "np:stop"
CID_RADIO = "np:radio"
CID_SHUFFLE = "np:shuffle"
CID_LOOP = "np:loop"
CID_VOLUME_DOWN = "np:vol_down"
CID_VOLUME_UP = "np:vol_up"
CID_QUEUE = "np:queue"
CID_JUMP = "np:jump"

VOLUME_STEP = 10
VOLUME_MAX = 200
#: Tracks listed under "Далее" in the panel itself.
UP_NEXT_PREVIEW = 3
#: Options in the jump list; Discord allows at most 25.
JUMP_OPTIONS = 25
#: Discord limits select option labels and descriptions to 100 characters.
OPTION_TEXT_LIMIT = 100

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
    "youtube": 0xFF0033,
    "spotify": SPOTIFY_COLOR,
    "local": 0x57F287,
    "soundcloud": 0xFF5500,
}
_DEFAULT_SOURCE_COLOR = 0xFFD966
_IDLE_COLOR = 0x4F545C

_LOOP_NEXT = {
    # Off -> whole queue -> this track -> off: the order Spotify cycles in.
    wavelink.QueueMode.normal: wavelink.QueueMode.loop_all,
    wavelink.QueueMode.loop_all: wavelink.QueueMode.loop,
    wavelink.QueueMode.loop: wavelink.QueueMode.normal,
}


# --------------------------------------------------------------------------- #
#  Text pieces
# --------------------------------------------------------------------------- #
def plain(text: str | None) -> str:
    """Escape a title for markdown, so ``*`` or ``_`` in it cannot restyle the panel."""
    return escape_markdown(text or "").replace("[", "\\[").replace("]", "\\]")


def requester_of(track: wavelink.Playable) -> str | None:
    """Display name of whoever queued the track, if it was recorded."""
    extras = getattr(track, "extras", None)
    if extras is None:
        return None
    name = getattr(extras, "requester", None)
    return str(name) if name else None


def track_key(track: wavelink.Playable) -> str:
    """Stable identity for a track (same rule the cog uses for retries)."""
    return track.identifier or track.uri or track.title


def _length(track: wavelink.Playable) -> str:
    if is_live(track):
        return "LIVE"
    return format_ms(track.length) if track.length else "?:??"


def _state_line(track: wavelink.Playable, player: wavelink.Player) -> str:
    """Where playback is.

    The end time is a Discord timestamp the *client* counts down, so the line
    stays truthful without the bot editing the message every second. A
    rendered "1:01 / 3:35" would be wrong a second after it was sent.
    """
    if is_live(track):
        return "🔴 **Прямой эфир**" + (" · ⏸️ на паузе" if player.paused else "")
    if player.paused:
        return f"⏸️ **На паузе** · {format_ms(player.position)} из {_length(track)}"
    if not track.length:
        return "▶️ **Играет**"
    ends_at = int(time.time() + max(0, track.length - player.position) / 1000)
    return f"▶️ **Играет** · {_length(track)} · закончится <t:{ends_at}:R>"


def _chips(player: wavelink.Player, radio: bool) -> str:
    chips = [f"🔊 {player.volume}%"]
    if player.queue.mode is wavelink.QueueMode.loop:
        chips.append("🔂 повтор трека")
    elif player.queue.mode is wavelink.QueueMode.loop_all:
        chips.append("🔁 повтор очереди")
    if radio:
        chips.append("📻 радио")
    return "-# " + " · ".join(chips)


def _up_next(player: wavelink.Player, radio: bool) -> str:
    queue = player.queue
    if queue.is_empty:
        if not radio:
            return (
                "**Далее**\n-# Очередь пуста — добавьте трек через `/play` или включите 📻 радио."
            )
        picks = list(player.auto_queue)[:UP_NEXT_PREVIEW]
        if not picks:
            return "**Далее**\n-# 📻 Радио подберёт похожий трек, когда этот закончится."
        lines = ["**Далее** · 📻 радио"]
        for index, track in enumerate(picks, 1):
            lines.append(f"`{index}.` {plain(track.title)} · {_length(track)}")
        return "\n".join(lines)
    lines = ["**Далее**"]
    for index, track in enumerate(list(queue)[:UP_NEXT_PREVIEW], 1):
        lines.append(f"`{index}.` {plain(track.title)} · {_length(track)}")
    rest = len(queue) - UP_NEXT_PREVIEW
    total = sum(t.length for t in queue if not is_live(t) and t.length)
    footer = []
    if rest > 0:
        footer.append(f"ещё {rest}")
    footer.append(f"в очереди {len(queue)}")
    if total:
        footer.append(f"всего {format_ms(total)}")
    lines.append("-# " + " · ".join(footer))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Controls
# --------------------------------------------------------------------------- #
class _Controls(ui.ActionRow["NowPlayingView"]):
    """Shared guard for every control that changes playback."""

    async def _allowed(self, interaction: discord.Interaction) -> bool:
        """DJ role, same voice channel, and not hammering the buttons.

        Answers the interaction itself when refusing, so callers just return.
        """
        view = self.view
        if (
            view is None
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            # Every path must answer, or Discord shows the press as failed.
            await interaction.response.send_message(
                "❌ Управление доступно только на сервере.", ephemeral=True
            )
            return False
        retry = view.cog.button_cooldown(interaction.user.id)
        if retry:
            await interaction.response.send_message(
                f"⏳ Не так быстро — подождите {retry:.0f} с.", ephemeral=True
            )
            return False
        if not await user_is_dj(view.cog.bot, interaction.user):
            await interaction.response.send_message(MSG_NEED_DJ, ephemeral=True)
            return False
        refusal = bot_voice_refusal(interaction.user)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return False
        # A panel from before a restart becomes the live one, whatever was
        # pressed, so the next track replaces it rather than stranding it.
        view.cog.adopt_panel(interaction)
        return True

    async def _player(self, interaction: discord.Interaction) -> wavelink.Player | None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(MSG_BOT_NOT_CONNECTED, ephemeral=True)
        return player

    async def _redraw(self, interaction: discord.Interaction, player: wavelink.Player) -> None:
        """Acknowledge by redrawing the pressed panel in one call.

        ``edit_message`` both answers the interaction and updates the panel,
        so there is no "thinking..." flash and no second request.
        """
        view = self.view
        assert view is not None
        if player.current is None:
            await interaction.response.defer()
            return
        await interaction.response.edit_message(
            view=now_playing_panel(player.current, player, view.cog)
        )
        # Pressed somewhere else - the private /now copy, say: the public
        # panel must not go on showing the old state.
        live = view.cog.now_messages.get(interaction.guild_id or 0)
        pressed = interaction.message
        if live is not None and (pressed is None or live.id != pressed.id):
            await view.cog.refresh_now_message(player)


class TransportRow(_Controls):
    """⏮ ⏯ ⏭ ⏹ 📻"""

    def __init__(self, player: wavelink.Player | None = None, *, radio: bool = False) -> None:
        super().__init__()
        if radio:
            self.radio.style = discord.ButtonStyle.success
        idle = player is None or player.current is None
        self.back.disabled = idle
        self.play_pause.disabled = idle
        self.skip.disabled = idle and (player is None or player.queue.is_empty)
        paused = player is not None and player.paused
        # The control shows the action it will perform.
        self.play_pause.emoji = "▶️" if paused else "⏸️"

    @ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id=CID_BACK)
    async def back(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        await interaction.response.defer()
        if not await self.view.cog.go_back(player, interaction.user):
            await _whisper(interaction, MSG_NOTHING_PLAYING)

    @ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id=CID_PLAY_PAUSE)
    async def play_pause(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        if player.current is None:
            await interaction.response.send_message(MSG_NOTHING_PLAYING, ephemeral=True)
            return
        await self.view.cog.toggle_pause(player, interaction.user, redraw=False)
        await self._redraw(interaction, player)

    @ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id=CID_SKIP)
    async def skip(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        # The next track_start replaces this panel, so only acknowledge here.
        await interaction.response.defer()
        if not await self.view.cog.skip_current(player, interaction.user):
            await _whisper(interaction, MSG_NOTHING_PLAYING)

    # NOT named `stop`: on a View that would shadow View.stop().
    @ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, custom_id=CID_STOP)
    async def stop_playback(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        await interaction.response.defer()
        await self.view.cog.stop_player(player, by=interaction.user)

    @ui.button(emoji="📻", style=discord.ButtonStyle.secondary, custom_id=CID_RADIO)
    async def radio(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None or interaction.guild is None:
            return
        cog = self.view.cog
        enabled = not cog.radio_on(interaction.guild.id)
        if player.current is not None:
            await cog.set_radio(player, enabled, interaction.user, redraw=False)
            await self._redraw(interaction, player)
            return
        # Nothing playing (a panel from before a restart): starting radio
        # looks tracks up first, which can outlast the three seconds Discord
        # allows for an answer.
        await interaction.response.defer()
        told = await cog.set_radio(
            player, enabled, interaction.user, channel_id=interaction.channel_id
        )
        await _whisper(interaction, told)


class ModesRow(_Controls):
    """🔀 🔁 🔉 🔊 📜"""

    def __init__(self, player: wavelink.Player | None = None) -> None:
        super().__init__()
        if player is None:
            return
        self.shuffle.disabled = len(player.queue) < 2
        self.volume_down.disabled = player.volume <= 0
        self.volume_up.disabled = player.volume >= VOLUME_MAX
        self.show_queue.disabled = player.queue.is_empty
        mode = player.queue.mode
        self.loop.emoji = "🔂" if mode is wavelink.QueueMode.loop else "🔁"
        self.loop.style = (
            discord.ButtonStyle.success
            if mode is not wavelink.QueueMode.normal
            else discord.ButtonStyle.secondary
        )

    @ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id=CID_SHUFFLE)
    async def shuffle(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        if not await self.view.cog.shuffle_queue(player, interaction.user, redraw=False):
            await interaction.response.send_message(
                "🔀 Перемешивать нечего — в очереди меньше двух треков.", ephemeral=True
            )
            return
        await self._redraw(interaction, player)

    @ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id=CID_LOOP)
    async def loop(self, interaction: discord.Interaction, _: ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        await self.view.cog.set_loop(
            player, _LOOP_NEXT[player.queue.mode], interaction.user, redraw=False
        )
        await self._redraw(interaction, player)

    @ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id=CID_VOLUME_DOWN)
    async def volume_down(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await self._nudge_volume(interaction, -VOLUME_STEP)

    @ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id=CID_VOLUME_UP)
    async def volume_up(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await self._nudge_volume(interaction, VOLUME_STEP)

    async def _nudge_volume(self, interaction: discord.Interaction, delta: int) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        target = max(0, min(VOLUME_MAX, player.volume + delta))
        if not await self.view.cog.set_volume(player, target, interaction.user, redraw=False):
            await interaction.response.send_message(
                "⚠️ Не удалось изменить громкость.", ephemeral=True
            )
            return
        await self._redraw(interaction, player)

    @ui.button(emoji="📜", style=discord.ButtonStyle.secondary, custom_id=CID_QUEUE)
    async def show_queue(self, interaction: discord.Interaction, _: ui.Button) -> None:
        # Looking is not steering: anyone may see the queue.
        player = player_of(interaction.guild)
        if player is None or (player.queue.is_empty and player.current is None):
            await interaction.response.send_message("🚫 Очередь пуста.", ephemeral=True)
            return
        await interaction.response.send_message(view=queue_view(player), ephemeral=True)


class JumpRow(_Controls):
    """Pick a queued track to play now."""

    def __init__(self, player: wavelink.Player | None = None) -> None:
        super().__init__()
        options: list[discord.SelectOption] = []
        if player is not None:
            for index, track in enumerate(list(player.queue)[:JUMP_OPTIONS]):
                label = f"{index + 1}. {track.title}"[:OPTION_TEXT_LIMIT]
                author = (track.author or "")[:60]
                options.append(
                    discord.SelectOption(
                        label=label,
                        # The key travels with the choice so a panel drawn
                        # before the queue changed cannot start the wrong track.
                        value=f"{index}:{track_key(track)}"[:OPTION_TEXT_LIMIT],
                        description=f"{author} · {_length(track)}"[:OPTION_TEXT_LIMIT],
                    )
                )
        as_select(self.jump).options = options

    @ui.select(placeholder="Перейти к треку из очереди…", custom_id=CID_JUMP)
    async def jump(self, interaction: discord.Interaction, select: ui.Select) -> None:
        if not await self._allowed(interaction):
            return
        player = await self._player(interaction)
        if player is None or self.view is None:
            return
        if not select.values:
            await interaction.response.defer()
            return
        index_text, _, key = select.values[0].partition(":")
        await interaction.response.defer()
        track = await self.view.cog.jump_to(
            player, int(index_text) if index_text.isdigit() else -1, key, interaction.user
        )
        if track is None:
            await _whisper(interaction, "🔄 Очередь изменилась — выберите трек ещё раз.")
            await self.view.cog.refresh_now_message(player)


async def _whisper(interaction: discord.Interaction, text: str) -> None:
    """Tell only the presser why nothing happened (the interaction is acknowledged)."""
    try:
        await interaction.followup.send(text, ephemeral=True)
    except discord.HTTPException:
        logger.debug("Could not send button feedback", exc_info=True)


# --------------------------------------------------------------------------- #
#  Views
# --------------------------------------------------------------------------- #
class NowPlayingView(PanelView):
    """The now-playing message: track card, state, up next, controls."""

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
            # Template registered with bot.add_view(): it only has to carry
            # the custom_ids, so presses on old panels reach these callbacks.
            container = make_panel(title="🎵 Сейчас играет")
            container.add_item(TransportRow())
            container.add_item(ModesRow())
            container.add_item(JumpRow())
            self.add_item(container)
            return

        source = (track.source or "").lower()
        accent = _SOURCE_COLORS.get(source, _DEFAULT_SOURCE_COLOR)
        title = plain(track.title)
        if track.uri:
            title = f"[{title}]({track.uri})"
        # The length lives in the state line below, next to the countdown.
        meta = [_SOURCE_NAMES.get(source, source.title() or "YouTube")]
        requester = requester_of(track)
        if is_radio_pick(track):
            meta.append("📻 подобрало радио")
        elif requester:
            meta.append(f"добавил {plain(requester)}")
        header = f"### {title}"
        if track.author:
            header += f"\n{plain(track.author)}"
        header += "\n-# " + " · ".join(meta)

        container = ui.Container(accent_colour=accent)
        if track.artwork:
            container.add_item(
                ui.Section(ui.TextDisplay(header), accessory=ui.Thumbnail(track.artwork))
            )
        else:
            container.add_item(ui.TextDisplay(header))
        radio = player.guild is not None and cog.radio_on(player.guild.id)
        container.add_item(ui.TextDisplay(f"{_state_line(track, player)}\n{_chips(player, radio)}"))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(_up_next(player, radio)))
        container.add_item(ui.Separator(visible=False))
        container.add_item(TransportRow(player, radio=radio))
        container.add_item(ModesRow(player))
        if not player.queue.is_empty:
            container.add_item(JumpRow(player))
        last = cog.last_action(player.guild.id) if player.guild is not None else None
        if last:
            container.add_item(ui.TextDisplay(f"-# {last}"))
        self.add_item(container)


def now_playing_panel(
    track: wavelink.Playable, player: wavelink.Player, cog: Music
) -> NowPlayingView:
    """Build the complete now-playing message for ``track``."""
    return NowPlayingView(cog, track=track, player=player)


def idle_panel(text: str, *, note: str | None = None) -> PanelView:
    """What the panel turns into when nothing plays: no buttons, one line."""
    view = PanelView(timeout=None)
    body = text if note is None else f"{text}\n-# {note}"
    view.add_item(make_panel(body=f"{body}\n-# `/play` — включить музыку", accent=_IDLE_COLOR))
    return view


def queue_view(player: wavelink.Player, *, page_size: int = 20) -> PanelView:
    """The full queue, for /queue and the 📜 button (shown privately)."""
    lines: list[str] = []
    if player.current is not None:
        lines.append(f"▶️ **{plain(player.current.title)}** · {_length(player.current)}\n")
    for index, track in enumerate(player.queue, 1):
        if index > page_size:
            lines.append(f"-# … и ещё {len(player.queue) - page_size}")
            break
        lines.append(f"`{index:>2}.` {plain(track.title)} · {_length(track)}")
    total = sum(t.length for t in player.queue if not is_live(t) and t.length)
    footer = [f"Треков в очереди: {len(player.queue)}"]
    if total:
        footer.append(f"общая длительность {format_ms(total)}")
    if player.queue.mode is wavelink.QueueMode.loop:
        footer.append("повтор трека")
    elif player.queue.mode is wavelink.QueueMode.loop_all:
        footer.append("повтор очереди")
    lines.append("-# " + " · ".join(footer))
    view = PanelView(timeout=None)
    view.add_item(make_panel(title="📜 Очередь", body="\n".join(lines)))
    return view
