"""Music commands backed by Lavalink via wavelink.

Per-guild state lives on the wavelink ``Player`` (one per guild) and its
``player.queue`` — there is no global state.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections import deque
from pathlib import Path

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.constants import (
    MSG_BOT_NOT_CONNECTED,
    MSG_JOIN_VOICE_FIRST,
    MSG_NOTHING_PLAYING,
    MSG_QUEUE_EMPTY,
)
from core.db import PlayerSession, SavedTrack
from ui.controls import (
    NowPlayingView,
    idle_panel,
    now_playing_panel,
    plain,
    queue_view,
    track_key,
)
from ui.search import SearchView
from ui.v2 import PanelView, make_panel
from utils.checks import guild_authorized, has_dj, in_bot_voice, in_command_channel
from utils.formatting import format_duration, format_ms, parse_position
from utils.links import spotify_search_text, youtube_video_only
from utils.playback_failures import (
    MAX_PLAY_RETRIES,
    Decision,
    FailureTracker,
    Verdict,
    classify,
)
from utils.player import connect_and_configure, is_live, player_of
from utils.radio import (
    RADIO_MEMORY,
    choose,
    is_radio_pick,
    mark_radio_pick,
    mix_url,
    seed_search,
    youtube_seed,
)

logger = logging.getLogger("bot.music")

SEARCH_RESULTS = 5
QUEUE_PAGE = 20
#: Discord shows at most 25 autocomplete choices, each name up to 100 chars.
AUTOCOMPLETE_LIMIT = 25
AUTOCOMPLETE_LABEL_LIMIT = 100

LOOP_MODES = {
    "off": wavelink.QueueMode.normal,
    "track": wavelink.QueueMode.loop,
    "queue": wavelink.QueueMode.loop_all,
}
LOOP_REPLIES = {
    "off": "➡️ Повтор выключен.",
    "track": "🔂 Повтор текущего трека.",
    "queue": "🔁 Повтор всей очереди.",
}

#: Back restarts the current track when further in than this, and only goes
#: to the previous track near the start - what Spotify and YouTube Music do.
BACK_RESTART_MS = 5_000

#: Panel buttons a user may press within ``BUTTON_WINDOW_S`` seconds. Enough
#: for a few volume clicks; stops a held-down mouse from flooding Discord.
BUTTON_RATE = 6
BUTTON_WINDOW_S = 10.0

#: "Track added" replies are removed after this many seconds: the panel's
#: "Далее" list already shows what was added, and by whom.
ADDED_NOTICE_TTL = 60.0
#: Failure notices stay a little longer - they explain something.
FAILURE_NOTICE_TTL = 120.0

LOOP_NOTES = {
    wavelink.QueueMode.normal: "➡️ Повтор выключен",
    wavelink.QueueMode.loop: "🔂 Повтор трека",
    wavelink.QueueMode.loop_all: "🔁 Повтор очереди",
}

#: Search prefixes understood by Lavalink and its plugins. A query that already
#: starts with one must be passed through untouched: wavelink only skips adding
#: its own prefix for URLs, so ``spsearch:foo`` would otherwise be sent as
#: ``ytsearch:spsearch:foo`` and match nothing.
SOURCE_PREFIXES = (
    "ytsearch:",
    "ytmsearch:",
    "scsearch:",
    "spsearch:",
    "sprec:",
    "dzsearch:",
    "dzisrc:",
    "amsearch:",
    "local:",
)

#: Hosts served by the LavaSrc Spotify source.
SPOTIFY_HOSTS = ("open.spotify.com", "play.spotify.com", "spotify.link")

#: Spotify link kinds whose contents cannot be listed by a bot.
#:
#: Both were verified against the live Web API, and both come from Spotify's
#: February 2026 Developer Mode migration rather than from this bot:
#:
#: * albums — LavaSrc hydrates them through ``GET /v1/tracks?ids=``, which
#:   Spotify **removed** in that migration, so the call answers 403. A future
#:   LavaSrc release could switch to ``/v1/albums/{id}/tracks``, which still
#:   works, so this one may start working again on its own.
#: * playlists — ``GET /v1/playlists/{id}/items`` now answers 401 "valid user
#:   authentication required": it needs a logged-in user, which a
#:   client-credentials bot does not have.
SPOTIFY_BULK_PATHS = ("/album/", "/playlist/")

#: Artist pages: LavaSrc loads them through ``GET /v1/artists/{id}/top-tracks``,
#: which answered 403 Forbidden in production on 2026-10-03.
SPOTIFY_ARTIST_PATH = "/artist/"

#: Track-end reasons that genuinely mean "there is nothing more to play".
#: Lavalink also sends "loadFailed" (already reported by the exception
#: handler), "replaced" and "cleanup" (not endings). See
#: https://lavalink.dev/api/websocket#track-end-reason
QUEUE_ENDING_REASONS = frozenset({"finished", "stopped"})

#: What the YouTube source says when every client came back without a stream
#: URL. With the cipher server down it is the *only* reason given; with it up
#: it appears next to other clients' reasons and means a SABR-only answer.
CIPHER_FAILURE_SIGNATURE = "No supported audio streams available"

#: wavelink's AutoPlay gives up for good once this many tracks in a row end
#: with "loadFailed" (``Player._error_count``, checked in
#: ``Player._auto_play_event``). Every retry is one such end, so left alone the
#: retries alone would trip it and freeze the rest of the queue - which is how
#: "the queue breaks after a bad track" happened. The cog therefore sets the
#: counter itself: zero to carry on, this value to stop on purpose.
WAVELINK_AUTOPLAY_ERROR_LIMIT = 3

__all__ = ["MAX_PLAY_RETRIES", "Music", "setup"]

MSG_SPOTIFY_DISABLED = (
    "⚠️ Spotify не настроен на этом сервере.\n"
    "Владельцу бота нужно задать `SPOTIFY_CLIENT_ID` и `SPOTIFY_CLIENT_SECRET` "
    "и перезапустить Lavalink."
)

MSG_SPOTIFY_BULK = (
    "⚠️ Альбомы и плейлисты Spotify не открываются.\n"
    "Spotify закрыл доступ к их составу для ботов в обновлении Web API "
    "(февраль 2026) — это ограничение на его стороне, не в боте.\n\n"
    "**Что работает:** ссылка на отдельный трек Spotify, поиск "
    "`spsearch: название`, плейлисты и альбомы **YouTube**."
)

MSG_SPOTIFY_ARTIST = (
    "⚠️ Страницы исполнителей Spotify не открываются.\n"
    "Spotify не отдаёт ботам популярные треки исполнителя (отвечает «доступ "
    "запрещён») — это ограничение на его стороне, не в боте.\n\n"
    "**Что работает:** ссылка на отдельный трек Spotify или просто имя "
    "исполнителя в `/play`."
)

#: Added to the reply when a video-in-playlist link fell back to the video.
MSG_PLAYLIST_UNAVAILABLE = (
    "-# Плейлист из ссылки недоступен (приватный или удалён) — добавлено только видео."
)


def _with_note(text: str, note: str | None) -> str:
    return f"{text}\n{note}" if note else text


def _set_autoplay_errors(player: wavelink.Player, count: int) -> None:
    """Set wavelink's consecutive-failure counter (see WAVELINK_AUTOPLAY_ERROR_LIMIT).

    wavelink exposes no public way to do this. tests/test_playback_recovery.py
    fails if an upgrade renames the attribute, rather than letting the queue
    quietly freeze again.
    """
    if hasattr(player, "_error_count"):
        player._error_count = count


class SpotifyNotConfigured(Exception):
    """A Spotify query arrived but the LavaSrc credentials are absent."""


class SpotifyLinkUnsupported(Exception):
    """A Spotify link whose contents Spotify will not serve to a bot.

    The message is the explanation for the user.
    """


class Music(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        # Per-guild now-playing message and the channel where commands were used.
        self.now_messages: dict[int, discord.Message] = {}
        self.home_channels: dict[int, int] = {}
        self._restored = False
        # Guilds currently being torn down by stop_player: the forced skip fires
        # on_wavelink_track_end, which would otherwise re-save the session we are
        # about to delete.
        self._stopping: set[int] = set()
        # Which track is being attempted and how often, per guild. Only the
        # policy lives there; the cog carries its verdicts out.
        self._failures = FailureTracker()
        # Last playback position Lavalink reported, per guild. player.position
        # cannot be used at failure time: when Lavalink's exception and end
        # events arrive together, wavelink has already cleared player.current
        # (and with it the position) before the exception listener runs.
        self._positions: dict[int, int] = {}
        # The latest playback action per guild, shown at the foot of the panel
        # so everyone sees who paused or skipped, without a chat message each.
        self._last_actions: dict[int, tuple[str, int]] = {}
        # Recent button presses per user, for BUTTON_RATE.
        self._presses: dict[int, deque[float]] = {}
        # One panel operation at a time per guild. Each is several Discord
        # calls (delete the old panel, post the new one, record it); two track
        # starts in quick succession interleaved at those awaits, both deleted
        # "the old" panel, both posted, and one panel was left behind with
        # live buttons.
        self._panel_locks: dict[int, asyncio.Lock] = {}
        # Radio (see utils/radio.py): the guilds that have it on, what each
        # guild played lately so radio does not repeat itself, and one radio
        # step at a time per guild - a track end and a skip can ask together.
        self._radio: set[int] = set()
        self._played: dict[int, deque[str]] = {}
        self._radio_locks: dict[int, asyncio.Lock] = {}
        # Guilds where a radio pick failed for good: radio moves on at its
        # loadFailed end, which the end handler otherwise ignores.
        self._radio_resume: set[int] = set()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    async def ensure_player(self, interaction: discord.Interaction) -> wavelink.Player | None:
        """Return the guild player, connecting to the user's channel if needed."""
        player = player_of(interaction.guild)
        if player is not None:
            return player
        user = interaction.user
        if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
            return None
        return await connect_and_configure(user.voice.channel, self.bot)

    @staticmethod
    def _set_requester(track: wavelink.Playable, member: discord.Member) -> None:
        track.extras = {
            "requester": member.display_name,
            "avatar": member.display_avatar.url,
        }

    def _track_too_long(self, track: wavelink.Playable) -> bool:
        max_seconds = self.bot.settings.max_track_length
        if max_seconds <= 0 or is_live(track) or not track.length:
            return False
        return track.length / 1000 > max_seconds

    def _local_file(self, query: str) -> str | None:
        """Map ``query`` to a path inside the Lavalink music volume, if it is one.

        The query comes straight from a user, so the resolved path must be
        confined to ``music_folder``: without the containment check a query like
        ``../../etc/passwd`` would escape it.
        """
        base = Path(self.bot.settings.music_folder).resolve()
        try:
            candidate = (base / query).resolve()
            relative = candidate.relative_to(base)
        except (ValueError, OSError):  # outside the base, or an unusable path
            return None
        if not candidate.is_file():
            return None
        container_dir = self.bot.settings.lavalink_local_dir.rstrip("/")
        return f"{container_dir}/{relative.as_posix()}"

    @staticmethod
    def _is_spotify(query: str) -> bool:
        lowered = query.lower()
        if lowered.startswith(("spsearch:", "sprec:")):
            return True
        return any(host in lowered for host in SPOTIFY_HOSTS)

    @classmethod
    def _is_spotify_bulk(cls, query: str) -> bool:
        """A Spotify album or playlist link, whose contents Spotify withholds."""
        lowered = query.lower()
        return cls._is_spotify(lowered) and any(part in lowered for part in SPOTIFY_BULK_PATHS)

    @classmethod
    def _is_spotify_artist(cls, query: str) -> bool:
        lowered = query.lower()
        return cls._is_spotify(lowered) and SPOTIFY_ARTIST_PATH in lowered

    async def _resolve(self, query: str) -> wavelink.Search:
        """Turn a user query into tracks.

        Order matters: a local file wins over anything else, then an explicit
        source prefix is honoured as given, and only a bare query falls back to
        a YouTube search. Spotify links need no special handling beyond the
        credential check — Lavalink's LavaSrc source manager claims the URL, and
        wavelink never prefixes a URL.
        """
        # A link to Spotify's search page carries words, not a track.
        query = spotify_search_text(query) or query
        if self._is_spotify(query):
            if not self.bot.settings.spotify_enabled:
                raise SpotifyNotConfigured
            # Fail fast with an explanation rather than letting LavaSrc hit
            # the endpoint Spotify refuses and surface "nothing found".
            if self._is_spotify_bulk(query):
                raise SpotifyLinkUnsupported(MSG_SPOTIFY_BULK)
            if self._is_spotify_artist(query):
                raise SpotifyLinkUnsupported(MSG_SPOTIFY_ARTIST)

        # is_file() hits the filesystem; keep the blocking syscall off the loop.
        local_path = await asyncio.to_thread(self._local_file, query)
        if local_path is not None:
            return await wavelink.Playable.search(local_path)

        if query.lower().startswith(SOURCE_PREFIXES):
            # source=None: the caller already chose the source.
            return await wavelink.Playable.search(query, source=None)

        return await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTube)

    async def _lookup(self, query: str) -> tuple[wavelink.Search, str | None]:
        """``_resolve``, plus the one recovery a failed link allows.

        Returns the result and a note for the user when it is not quite what
        they pasted.
        """
        try:
            return await self._resolve(query), None
        except wavelink.LavalinkLoadException:
            video = youtube_video_only(query)
            if video is None:
                raise
        logger.info("The playlist in %r did not load; trying the video alone", query)
        return await self._resolve(video), MSG_PLAYLIST_UNAVAILABLE

    # ------------------------------------------------------------------ #
    #  Radio
    # ------------------------------------------------------------------ #
    def radio_on(self, guild_id: int) -> bool:
        return guild_id in self._radio

    async def set_radio(
        self,
        player: wavelink.Player,
        enabled: bool,
        user: discord.abc.User | None,
        *,
        redraw: bool = True,
        channel_id: int | None = None,
    ) -> str:
        """Turn radio on or off. Returns what to tell whoever did it.

        Turned on with nothing playing, radio starts at once from the last
        track played: otherwise "on" did nothing visible until someone played
        a track, which looked exactly like radio not working.
        """
        if player.guild is None:
            return MSG_BOT_NOT_CONNECTED
        guild_id = player.guild.id
        if channel_id is not None:
            self.home_channels[guild_id] = channel_id
        self.note_action(guild_id, user, "📻 Радио включено" if enabled else "📻 Радио выключено")
        if not enabled:
            self._radio.discard(guild_id)
            player.auto_queue.clear()
            if redraw:
                await self.refresh_now_message(player)
            return "📻 Радио выключено."
        self._radio.add(guild_id)
        if player.current is not None or not player.queue.is_empty:
            if redraw:
                await self.refresh_now_message(player)
            return (
                "📻 Радио включено — когда очередь закончится, музыка продолжится похожими треками."
            )
        seed = self._last_played(player)
        if seed is None:
            return (
                "📻 Радио включено. Включите любой трек через `/play` — "
                "после него музыка будет подбираться сама."
            )
        if await self.radio_next(player, seed, fresh_start=True):
            return f"📻 Радио включено — подбираю похожее на «{plain(seed.title)}»."
        return "📻 Радио включено, но похожих треков не нашлось. Включите трек через `/play`."

    @staticmethod
    def _last_played(player: wavelink.Player) -> wavelink.Playable | None:
        history = player.queue.history
        if history is None or history.is_empty:
            return None
        return history[-1]

    def _radio_may_play(self, player: wavelink.Player) -> bool:
        """Radio is on and nothing else is about to play."""
        if player.guild is None:
            return False
        guild_id = player.guild.id
        return (
            guild_id in self._radio
            and guild_id not in self._stopping
            and player.current is None
            and player.queue.is_empty
            # Repeat modes carry on by themselves; radio would play over them.
            and player.queue.mode is wavelink.QueueMode.normal
        )

    async def radio_next(
        self,
        player: wavelink.Player,
        seed: wavelink.Playable | None = None,
        *,
        fresh_start: bool = False,
    ) -> bool:
        """Play radio's next pick. False when radio has nothing to play.

        ``seed`` is the track that just ended; without one, the last track
        played. ``fresh_start`` marks a person asking (a skip, turning radio
        on): only then does a run of failed picks start counting again, or a
        source that refuses every pick would keep radio failing forever.
        """
        if player.guild is None:
            return False
        guild_id = player.guild.id
        async with self._radio_locks.setdefault(guild_id, asyncio.Lock()):
            if not self._radio_may_play(player):
                return False
            picks = player.auto_queue
            track = self._next_pick(picks, guild_id)
            if track is None:
                seed = seed or self._last_played(player)
                if seed is None:
                    return False
                for pick in await self._radio_picks(seed, guild_id):
                    mark_radio_pick(pick)
                    picks.put(pick)
                if not self._radio_may_play(player):
                    # Someone queued a track or stopped while radio was
                    # looking; the picks wait for the next time.
                    return False
                track = self._next_pick(picks, guild_id)
            if track is None:
                logger.info(
                    "Radio found nothing like %r in guild %s",
                    seed.title if seed else None,
                    guild_id,
                )
                return False
            if fresh_start:
                self._failures.resume_queue(guild_id)
            _set_autoplay_errors(player, 0)
            logger.info("Radio plays %r in guild %s", track.title, guild_id)
            await player.play(track, paused=False)
            return True

    def _next_pick(self, picks: wavelink.Queue, guild_id: int) -> wavelink.Playable | None:
        played = self._played.get(guild_id, ())
        while not picks.is_empty:
            track = picks.get()
            if self._track_key(track) not in played:
                return track
        return None

    async def _radio_picks(self, seed: wavelink.Playable, guild_id: int) -> list[wavelink.Playable]:
        """Tracks like ``seed``, from YouTube's mix for it."""
        video = youtube_seed(seed)
        if video is None:
            query = seed_search(seed)
            found = await self._radio_search(query) if query else []
            video = youtube_seed(found[0]) if found else None
        if video is None:
            return []
        mix = await self._radio_search(mix_url(video))
        played = {*self._played.get(guild_id, ()), video}
        return choose(mix, played=played, too_long=self._track_too_long)

    async def _radio_search(self, query: str) -> list[wavelink.Playable]:
        try:
            result = await wavelink.Playable.search(query, source=None)
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException) as error:
            logger.warning("Radio lookup failed for %r: %s", query, error)
            return []
        if isinstance(result, wavelink.Playlist):
            return list(result.tracks)
        return list(result)

    async def maybe_start(self, player: wavelink.Player) -> None:
        if not player.playing and not player.queue.is_empty:
            if player.guild is not None:
                # Someone asked for music, so a queue paused after repeated
                # failures gets another chance.
                self._failures.resume_queue(player.guild.id)
            _set_autoplay_errors(player, 0)
            # Explicitly unpaused: wavelink starts a track in whatever pause
            # state the player was left in, so after /stop or a skip while
            # paused the next /play would start silently.
            await player.play(player.queue.get(), paused=False)

    async def skip_current(
        self, player: wavelink.Player, user: discord.abc.User | None = None
    ) -> bool:
        """Move to the next track. False when there is nothing to move to.

        Shared by /skip and the panel button so both behave the same in the
        two states where wavelink's own ``skip`` silently does nothing:

        * a retry of a failed track is queued but has not started - skipping
          must withdraw it, or the "skipped" track simply comes back;
        * the queue was paused after repeated failures - nothing is loaded, so
          there is nothing for ``skip`` to stop and no event would follow.
        """
        if player.guild is None:
            return False
        queue = player.queue
        withdrawn = self._failures.cancel_pending(player.guild.id)
        if (
            withdrawn is not None
            and not queue.is_empty
            and self._track_key(queue.peek(0)) == withdrawn
        ):
            queue.delete(0)
        if player.current is not None:
            self.note_action(player.guild.id, user, "⏭️ Пропущен трек")
            was_paused = player.paused
            await player.skip(force=True)
            if was_paused:
                # Every player resumes when you skip while paused. Left alone,
                # AutoPlay starts the next track in the inherited pause state,
                # silently - which looked like the skip had not worked. Either
                # this lands before AutoPlay's play (which then starts
                # unpaused) or after it (and unpauses it); both end playing.
                await player.pause(False)
            return True
        if not queue.is_empty:
            self.note_action(player.guild.id, user, "⏭️ Очередь продолжена")
            self._failures.resume_queue(player.guild.id)
            _set_autoplay_errors(player, 0)
            await player.play(queue.get(), paused=False)
            return True
        if self.radio_on(player.guild.id) and await self.radio_next(player, fresh_start=True):
            self.note_action(player.guild.id, user, "⏭️ Радио продолжено")
            return True
        return withdrawn is not None

    # ------------------------------------------------------------------ #
    #  Controls shared by slash commands and the panel
    # ------------------------------------------------------------------ #
    # Each changes the player, records who did it, and redraws the panel
    # unless the caller redraws it itself (a button answers by editing the
    # pressed message, which acknowledges the interaction in the same call).
    async def set_paused(
        self,
        player: wavelink.Player,
        paused: bool,
        user: discord.abc.User | None,
        *,
        redraw: bool = True,
    ) -> None:
        await player.pause(paused)
        if player.guild is not None:
            self.note_action(player.guild.id, user, "⏸️ Пауза" if paused else "▶️ Продолжено")
        if redraw:
            await self.refresh_now_message(player)

    async def toggle_pause(
        self, player: wavelink.Player, user: discord.abc.User | None, *, redraw: bool = True
    ) -> bool:
        paused = not player.paused
        await self.set_paused(player, paused, user, redraw=redraw)
        return paused

    async def go_back(self, player: wavelink.Player, user: discord.abc.User | None) -> bool:
        """⏮: restart the track, or play the previous one near its start.

        False when nothing is playing. The previous track is the history entry
        before the current one; the current track goes back to the head of the
        queue, so pressing ⏭ afterwards returns to it, as in any player.
        """
        current = player.current
        if current is None or player.guild is None:
            return False
        guild_id = player.guild.id
        history = player.queue.history
        items = list(history) if history is not None else []
        here = (
            len(items) - 1 if items and track_key(items[-1]) == track_key(current) else len(items)
        )
        if player.position > BACK_RESTART_MS or here == 0 or history is None:
            if current.is_seekable and not is_live(current):
                self.note_action(guild_id, user, "⏮️ Трек сначала")
                await player.seek(0)
                await self.refresh_now_message(player)
            return True
        previous = items[here - 1]
        if here < len(items):
            history.delete(here)
        history.delete(here - 1)
        player.queue.put_at(0, current)
        self.note_action(guild_id, user, "⏮️ Предыдущий трек")
        # play() adds it back to history, and replacing the current track ends
        # it as "replaced", which AutoPlay leaves alone.
        await player.play(previous, paused=False)
        await self.persist_queue(player)
        return True

    async def jump_to(
        self,
        player: wavelink.Player,
        index: int,
        key: str,
        user: discord.abc.User | None,
    ) -> wavelink.Playable | None:
        """Play a queued track now, dropping the ones before it (as Spotify does).

        ``key`` identifies the track the user saw. If the queue changed since
        the panel was drawn, the same track is looked up again; if it is gone,
        nothing happens and None is returned.
        """
        if player.guild is None:
            return None
        queue = player.queue
        items = list(queue)
        if not (0 <= index < len(items) and track_key(items[index]) == key):
            index = next((i for i, t in enumerate(items) if track_key(t) == key), -1)
            if index < 0:
                return None
        track = items[index]
        self._failures.cancel_pending(player.guild.id)
        for _ in range(index + 1):
            queue.delete(0)
        if queue.mode is wavelink.QueueMode.loop_all and queue.history is not None:
            for skipped in items[:index]:  # they come round again with the queue
                queue.history.put(skipped)
        self.note_action(player.guild.id, user, f"⤵️ Включён «{plain(track.title)}»")
        await player.play(track, paused=False)
        await self.persist_queue(player)
        return track

    async def shuffle_queue(
        self, player: wavelink.Player, user: discord.abc.User | None, *, redraw: bool = True
    ) -> bool:
        if len(player.queue) < 2 or player.guild is None:
            return False
        player.queue.shuffle()
        self.note_action(player.guild.id, user, "🔀 Очередь перемешана")
        await self.persist_queue(player)
        if redraw:
            await self.refresh_now_message(player)
        return True

    async def set_loop(
        self,
        player: wavelink.Player,
        mode: wavelink.QueueMode,
        user: discord.abc.User | None,
        *,
        redraw: bool = True,
    ) -> None:
        player.queue.mode = mode
        if player.guild is not None:
            self.note_action(player.guild.id, user, LOOP_NOTES[mode])
        if redraw:
            await self.refresh_now_message(player)

    async def set_volume(
        self,
        player: wavelink.Player,
        value: int,
        user: discord.abc.User | None,
        *,
        redraw: bool = True,
    ) -> bool:
        try:
            await player.set_volume(value)
        except (wavelink.LavalinkException, wavelink.NodeException):
            logger.warning("Could not set the volume", exc_info=True)
            return False
        if player.guild is not None:
            self.note_action(player.guild.id, user, f"🔊 Громкость {value}%")
        if redraw:
            await self.refresh_now_message(player)
        return True

    async def _announce(self, interaction: discord.Interaction, text: str) -> None:
        """A public reply that removes itself after ADDED_NOTICE_TTL."""
        message = await interaction.followup.send(text, wait=True)
        with contextlib.suppress(discord.HTTPException):
            await message.delete(delay=ADDED_NOTICE_TTL)

    @staticmethod
    def _to_saved(track: wavelink.Playable) -> SavedTrack:
        extras = getattr(track, "extras", None)
        return SavedTrack(
            uri=track.uri or "",
            requester=getattr(extras, "requester", None) if extras else None,
            avatar=getattr(extras, "avatar", None) if extras else None,
        )

    async def persist_queue(self, player: wavelink.Player) -> None:
        if player.guild is None or player.channel is None:
            return
        if player.guild.id in self._stopping:
            return  # teardown in progress; the session row is being deleted
        tracks: list[SavedTrack] = []
        if player.current is not None and player.current.uri:
            tracks.append(self._to_saved(player.current))
        tracks.extend(self._to_saved(t) for t in player.queue if t.uri)
        text_channel_id = self.home_channels.get(player.guild.id)
        try:
            await self.bot.db.save_session(
                player.guild.id, player.channel.id, text_channel_id, tracks
            )
        except sqlite3.Error:
            logger.exception("Failed to persist session")

    def _panel_lock(self, guild_id: int) -> asyncio.Lock:
        return self._panel_locks.setdefault(guild_id, asyncio.Lock())

    async def refresh_now_message(self, player: wavelink.Player) -> None:
        if player.guild is None:
            return
        async with self._panel_lock(player.guild.id):
            message = self.now_messages.get(player.guild.id)
            if message is not None and player.current is not None:
                try:
                    await message.edit(view=now_playing_panel(player.current, player, self))
                except discord.HTTPException:
                    pass

    async def clear_now_message(self, guild_id: int) -> None:
        async with self._panel_lock(guild_id):
            await self._drop_panel(guild_id)

    async def _drop_panel(self, guild_id: int) -> None:
        """Delete the live panel. Caller holds the panel lock."""
        message = self.now_messages.pop(guild_id, None)
        if message is not None:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            await self._forget_panel(guild_id)

    async def _post_panel(
        self,
        player: wavelink.Player,
        track: wavelink.Playable,
        channel: discord.abc.Messageable,
    ) -> None:
        """Replace the guild's panel with one for ``track``."""
        assert player.guild is not None
        guild_id = player.guild.id
        async with self._panel_lock(guild_id):
            await self._drop_panel(guild_id)
            try:
                message = await channel.send(view=now_playing_panel(track, player, self))
            except discord.HTTPException:
                logger.exception("Failed to send now-playing message")
                return
            self.now_messages[guild_id] = message
            try:
                await self.bot.db.save_now_panel(guild_id, message.channel.id, message.id)
            except sqlite3.Error:
                logger.exception("Failed to record the now-playing panel")

    async def retire_panel(self, guild_id: int, text: str, *, note: str | None = None) -> None:
        """Turn the live panel idle instead of deleting it.

        One message keeps the record ("queue ended", "stopped by X") where a
        deleted panel plus a fresh notice used to leave two, and the buttons go
        with it so nobody presses controls of a player that is gone.
        """
        async with self._panel_lock(guild_id):
            message = self.now_messages.pop(guild_id, None)
            if message is None:
                return
            try:
                await message.edit(view=idle_panel(text, note=note))
            except discord.HTTPException:
                logger.debug("Could not retire the now-playing panel", exc_info=True)
            await self._forget_panel(guild_id)

    async def _forget_panel(self, guild_id: int) -> None:
        try:
            await self.bot.db.clear_now_panel(guild_id)
        except sqlite3.Error:
            logger.exception("Failed to forget the now-playing panel")

    def adopt_panel(self, interaction: discord.Interaction) -> None:
        """Track a panel pressed after a restart as the live one.

        The process that posted it is gone, so it is in no dict; adopting it
        lets the next track replace it instead of leaving it behind.
        """
        message = interaction.message
        if (
            interaction.guild_id is None
            or message is None
            or message.flags.ephemeral
            or interaction.guild_id in self.now_messages
        ):
            return
        self.now_messages[interaction.guild_id] = message

    def note_action(self, guild_id: int, user: discord.abc.User | None, text: str) -> None:
        who = f" — {plain(user.display_name)}" if user is not None else ""
        self._last_actions[guild_id] = (f"{text}{who}", int(time.time()))

    def last_action(self, guild_id: int) -> str | None:
        entry = self._last_actions.get(guild_id)
        if entry is None:
            return None
        text, at = entry
        return f"{text} · <t:{at}:R>"

    def button_cooldown(self, user_id: int) -> float:
        """Seconds until ``user_id`` may press again; 0 when they may now."""
        now = time.monotonic()
        presses = self._presses.setdefault(user_id, deque())
        while presses and now - presses[0] > BUTTON_WINDOW_S:
            presses.popleft()
        if len(presses) >= BUTTON_RATE:
            return BUTTON_WINDOW_S - (now - presses[0])
        presses.append(now)
        return 0.0

    def _forget_guild(self, guild_id: int) -> None:
        """Drop per-guild bookkeeping so the dicts don't grow without bound."""
        self.home_channels.pop(guild_id, None)
        self.now_messages.pop(guild_id, None)
        self._failures.forget(guild_id)
        self._positions.pop(guild_id, None)
        self._last_actions.pop(guild_id, None)
        self._panel_locks.pop(guild_id, None)
        self._stopping.discard(guild_id)
        self._radio.discard(guild_id)
        self._played.pop(guild_id, None)
        self._radio_locks.pop(guild_id, None)
        self._radio_resume.discard(guild_id)

    async def stop_player(
        self, player: wavelink.Player, *, by: discord.abc.User | None = None
    ) -> None:
        if player.guild is None:
            return
        guild_id = player.guild.id
        self._stopping.add(guild_id)
        try:
            # Stop means silence: radio would otherwise answer the end of the
            # stopped track with a new one.
            self._radio.discard(guild_id)
            self._radio_resume.discard(guild_id)
            player.autoplay = wavelink.AutoPlayMode.partial
            player.queue.clear()
            player.auto_queue.clear()
            # Before the skip: its end event, and any event still in flight for
            # the track that was loading, must not report or redraw anything.
            self._failures.silence(guild_id)
            if player.playing or player.current is not None:
                await player.skip(force=True)
            if player.paused:
                await player.pause(False)  # so the next /play is heard
            who = f" — {plain(by.display_name)}" if by is not None else ""
            await self.retire_panel(guild_id, f"⏹️ Воспроизведение остановлено{who}")
            await self.bot.db.clear_session(guild_id)
        finally:
            self._stopping.discard(guild_id)

    async def add_and_play(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
        member: discord.Member,
    ) -> bool:
        """Enqueue a chosen track and start if idle. False if there is no player.

        The search menu relies on the return value: it must not report success
        when the requester has meanwhile left the voice channel.
        """
        player = await self.ensure_player(interaction)
        if player is None or interaction.guild is None:
            return False
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]
        self._set_requester(track, member)
        player.queue.put(track)
        await self.maybe_start(player)
        await self.refresh_now_message(player)
        await self.persist_queue(player)
        return True

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="play",
        description="Воспроизвести трек или плейлист: YouTube, Spotify, локальный файл",
    )
    @app_commands.describe(
        query="Ссылка (YouTube/Spotify), поисковый запрос или имя локального файла"
    )
    # Decorators evaluate bottom-up, so the cooldown listed first runs last:
    # an unauthorized guild is rejected before the bucket is consumed.
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    @in_bot_voice()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        if player is None or interaction.guild is None:
            await interaction.followup.send(MSG_JOIN_VOICE_FIRST)
            return
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]

        try:
            result, note = await self._lookup(query.strip())
        except SpotifyNotConfigured:
            await interaction.followup.send(MSG_SPOTIFY_DISABLED)
            return
        except SpotifyLinkUnsupported as refusal:
            await interaction.followup.send(str(refusal))
            return
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException) as error:
            # One line: the cause is all there is to know, and it is the
            # user's link that failed, not the bot.
            logger.warning("Search failed for %r: %s", query, error)
            await interaction.followup.send("⚠️ Не удалось загрузить трек по этому запросу.")
            return

        if not result:
            await interaction.followup.send("⚠️ По запросу ничего не найдено.")
            return

        if isinstance(result, wavelink.Playlist):
            tracks = [t for t in result.tracks if not self._track_too_long(t)]
            tracks = tracks[: self.bot.settings.max_playlist_tracks]
            if not tracks:
                await interaction.followup.send("⚠️ В плейлисте нет подходящих треков.")
                return
            for track in tracks:
                self._set_requester(track, interaction.user)  # type: ignore[arg-type]
                player.queue.put(track)
            await self._announce(
                interaction,
                _with_note(
                    f"🎵 Добавлен плейлист **{plain(result.name)}** — {len(tracks)} треков.",
                    note,
                ),
            )
        else:
            track = result[0]
            if self._track_too_long(track):
                limit = format_duration(self.bot.settings.max_track_length)
                await interaction.followup.send(f"⚠️ Трек длиннее лимита ({limit}).")
                return
            self._set_requester(track, interaction.user)  # type: ignore[arg-type]
            player.queue.put(track)
            await self._announce(
                interaction, _with_note(f"🎵 Добавлен трек: **{plain(track.title)}**", note)
            )

        await self.maybe_start(player)
        await self.refresh_now_message(player)  # "Далее" now lists it
        await self.persist_queue(player)

    @app_commands.command(name="search", description="Найти трек и выбрать из списка")
    @app_commands.describe(query="Поисковый запрос")
    # Decorators evaluate bottom-up, so the cooldown listed first runs last:
    # an unauthorized guild is rejected before the bucket is consumed.
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    @in_bot_voice()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if not isinstance(interaction.user, discord.Member) or interaction.user.voice is None:
            await interaction.followup.send(MSG_JOIN_VOICE_FIRST)
            return
        try:
            result, _note = await self._lookup(query.strip())
        except SpotifyNotConfigured:
            await interaction.followup.send(MSG_SPOTIFY_DISABLED)
            return
        except SpotifyLinkUnsupported as refusal:
            await interaction.followup.send(str(refusal))
            return
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException) as error:
            logger.warning("Search failed for %r: %s", query, error)
            await interaction.followup.send("⚠️ Ошибка поиска.")
            return
        if isinstance(result, wavelink.Playlist):
            result = result.tracks
        if not result:
            await interaction.followup.send("⚠️ Ничего не найдено.")
            return
        tracks = list(result)[:SEARCH_RESULTS]
        view = SearchView(self, tracks, interaction.user)
        # No `content`: a Components V2 message cannot carry one — the heading
        # is part of the view itself.
        await interaction.followup.send(view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="now", description="Показать текущий трек")
    @guild_authorized()
    async def now(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is None or player.current is None:
            await interaction.response.send_message(MSG_NOTHING_PLAYING, ephemeral=True)
            return
        await interaction.response.send_message(
            view=now_playing_panel(player.current, player, self), ephemeral=True
        )

    @app_commands.command(name="queue", description="Показать очередь")
    @guild_authorized()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is None or (player.queue.is_empty and player.current is None):
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        view = queue_view(player, page_size=QUEUE_PAGE)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="shuffle", description="Перемешать очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and await self.shuffle_queue(player, interaction.user):
            await interaction.response.send_message("🔀 Очередь перемешана.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "🔀 Перемешивать нечего — в очереди меньше двух треков.", ephemeral=True
            )

    @app_commands.command(name="clear", description="Очистить очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def clear(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and not player.queue.is_empty and interaction.guild:
            # A queued retry is part of the queue; clearing withdraws it too.
            self._failures.cancel_pending(interaction.guild.id)
            player.queue.clear()
            self.note_action(interaction.guild.id, interaction.user, "🧹 Очередь очищена")
            await self.persist_queue(player)
            await self.refresh_now_message(player)
            await interaction.response.send_message("🧹 Очередь очищена.", ephemeral=True)
        else:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)

    async def _queue_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        """Offer queue entries by position, filtered by what has been typed."""
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            return []
        needle = current.strip().lower()
        choices: list[app_commands.Choice[int]] = []
        for index, track in enumerate(player.queue, 1):
            label = f"{index}. {track.title}"
            if needle and needle not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:AUTOCOMPLETE_LABEL_LIMIT], value=index))
            if len(choices) >= AUTOCOMPLETE_LIMIT:
                break
        return choices

    @app_commands.command(name="volume", description="Громкость текущего воспроизведения")
    @app_commands.describe(value="Громкость в процентах, 0..200")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def volume(
        self,
        interaction: discord.Interaction,
        value: app_commands.Range[int, 0, 200],
    ) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(MSG_BOT_NOT_CONNECTED, ephemeral=True)
            return
        if not await self.set_volume(player, value, interaction.user):
            await interaction.response.send_message(
                "⚠️ Не удалось изменить громкость.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔊 Громкость: **{value}%** (только для текущей сессии — "
            "постоянное значение задаётся в `/settings volume`).",
            ephemeral=True,
        )

    @app_commands.command(name="seek", description="Перемотать текущий трек")
    @app_commands.describe(position="Позиция: 90, 1:30 или 1:02:03")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def seek(self, interaction: discord.Interaction, position: str) -> None:
        player = player_of(interaction.guild)
        if player is None or player.current is None:
            await interaction.response.send_message(MSG_NOTHING_PLAYING, ephemeral=True)
            return
        track = player.current
        if is_live(track) or not track.is_seekable:
            await interaction.response.send_message(
                "❌ Этот трек нельзя перематывать (прямой эфир).", ephemeral=True
            )
            return
        target = parse_position(position)
        if target is None:
            await interaction.response.send_message(
                "❌ Не понял позицию. Примеры: `90`, `1:30`, `1:02:03`.", ephemeral=True
            )
            return
        if track.length and target > track.length:
            await interaction.response.send_message(
                f"❌ Трек длится {format_ms(track.length)} — позиция за его пределами.",
                ephemeral=True,
            )
            return
        try:
            await player.seek(target)
        except (wavelink.LavalinkException, wavelink.NodeException):
            logger.warning("Seek failed", exc_info=True)
            await interaction.response.send_message("⚠️ Не удалось перемотать.", ephemeral=True)
            return
        if interaction.guild is not None:
            self.note_action(
                interaction.guild.id, interaction.user, f"⏩ Перемотано на {format_ms(target)}"
            )
        await self.refresh_now_message(player)
        await interaction.response.send_message(
            f"⏩ Перемотано на **{format_ms(target)}**.", ephemeral=True
        )

    @app_commands.command(name="loop", description="Режим повтора")
    @app_commands.describe(mode="Что повторять")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Выключить", value="off"),
            app_commands.Choice(name="Текущий трек", value="track"),
            app_commands.Choice(name="Всю очередь", value="queue"),
        ]
    )
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(MSG_BOT_NOT_CONNECTED, ephemeral=True)
            return
        await self.set_loop(player, LOOP_MODES[mode.value], interaction.user)
        await interaction.response.send_message(LOOP_REPLIES[mode.value], ephemeral=True)

    @app_commands.command(name="remove", description="Убрать трек из очереди")
    @app_commands.describe(position="Номер трека в очереди (см. /queue)")
    @app_commands.autocomplete(position=_queue_autocomplete)
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def remove(
        self, interaction: discord.Interaction, position: app_commands.Range[int, 1]
    ) -> None:
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        if position > len(player.queue):
            await interaction.response.send_message(
                f"❌ В очереди только {len(player.queue)} треков.", ephemeral=True
            )
            return
        index = position - 1  # the queue is 0-based, the command is 1-based
        title = plain(player.queue.peek(index).title)
        player.queue.delete(index)
        if interaction.guild is not None:
            self.note_action(interaction.guild.id, interaction.user, f"🗑️ Убран «{title}»")
        await self.persist_queue(player)
        await self.refresh_now_message(player)
        await interaction.response.send_message(f"🗑️ Убрано из очереди: **{title}**", ephemeral=True)

    @app_commands.command(name="move", description="Переместить трек в очереди")
    @app_commands.describe(position="Какой трек переместить", to="На какую позицию")
    @app_commands.autocomplete(position=_queue_autocomplete)
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def move(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1],
        to: app_commands.Range[int, 1],
    ) -> None:
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        size = len(player.queue)
        if position > size or to > size:
            await interaction.response.send_message(
                f"❌ В очереди только {size} треков.", ephemeral=True
            )
            return
        if position == to:
            await interaction.response.send_message("ℹ️ Трек уже на этой позиции.", ephemeral=True)
            return
        # peek + delete rather than get_at: get_at also assigns the track to the
        # queue's `_loaded` slot, which is what QueueMode.loop replays — moving
        # a track would silently change what is on repeat.
        track = player.queue.peek(position - 1)
        player.queue.delete(position - 1)
        player.queue.put_at(to - 1, track)
        await self.persist_queue(player)
        await self.refresh_now_message(player)
        await interaction.response.send_message(
            f"↕️ **{plain(track.title)}** — теперь на позиции **{to}**.", ephemeral=True
        )

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and await self.skip_current(player, interaction.user):
            await interaction.response.send_message("⏭️ Пропущено.", ephemeral=True)
        else:
            await interaction.response.send_message(MSG_NOTHING_PLAYING, ephemeral=True)

    @app_commands.command(name="pause", description="Пауза")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and player.playing and not player.paused:
            await self.set_paused(player, True, interaction.user)
            await interaction.response.send_message("⏸️ Пауза.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Нечего ставить на паузу.", ephemeral=True)

    @app_commands.command(name="resume", description="Продолжить")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and player.paused:
            await self.set_paused(player, False, interaction.user)
            await interaction.response.send_message("▶️ Продолжаю.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Воспроизведение не на паузе.", ephemeral=True
            )

    @app_commands.command(name="stop", description="Остановить и очистить очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None:
            await self.stop_player(player, by=interaction.user)
            await interaction.response.send_message(
                "⏹️ Воспроизведение остановлено, очередь очищена.", ephemeral=True
            )
        else:
            await interaction.response.send_message(MSG_BOT_NOT_CONNECTED, ephemeral=True)

    @app_commands.command(
        name="autoplay", description="Радио: похожие треки, когда очередь закончится"
    )
    @app_commands.describe(mode="Включить или выключить радио")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Включить (радио)", value="on"),
            app_commands.Choice(name="Выключить", value="off"),
        ]
    )
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    @in_bot_voice()
    async def autoplay(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(MSG_BOT_NOT_CONNECTED, ephemeral=True)
            return
        # Starting radio from silence looks tracks up first, which can take
        # longer than Discord waits for an answer.
        await interaction.response.defer(ephemeral=True)
        told = await self.set_radio(
            player, mode.value == "on", interaction.user, channel_id=interaction.channel_id
        )
        await interaction.followup.send(told, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Wavelink events
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        player = payload.player
        if player is None or player.guild is None:
            return
        # A retry produces its own track_start. Reposting the panel for it made
        # the UI flicker once per attempt, and treating it as a new track reset
        # the attempt budget so the track retried forever.
        self._positions.pop(player.guild.id, None)
        key = self._track_key(payload.track)
        self._played.setdefault(player.guild.id, deque(maxlen=RADIO_MEMORY)).append(key)
        if not is_radio_pick(payload.track):
            # Someone chose this track: when the queue runs out, radio follows
            # it rather than the picks it made for an earlier one.
            player.auto_queue.clear()
        is_retry, resume_ms = self._failures.on_start(player.guild.id, key)
        logger.info(
            "%s %r in guild %s",
            "Retry started" if is_retry else "Now playing",
            payload.track.title,
            player.guild.id,
        )
        if is_retry:
            if resume_ms and payload.track.is_seekable:
                with contextlib.suppress(wavelink.LavalinkException, wavelink.NodeException):
                    await player.seek(resume_ms)
            return

        channel_id = self.home_channels.get(player.guild.id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.abc.Messageable):
            return
        await self._post_panel(player, payload.track, channel)
        await self.persist_queue(player)

    @commands.Cog.listener()
    async def on_wavelink_player_update(self, payload: wavelink.PlayerUpdateEventPayload) -> None:
        player = payload.player
        if player is not None and player.guild is not None:
            self._positions[player.guild.id] = payload.position

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        player = payload.player
        if player is None or player.guild is None:
            return
        logger.info(
            "Track ended (%s): %r in guild %s, %d queued",
            payload.reason,
            payload.track.title,
            player.guild.id,
            len(player.queue),
        )
        if payload.reason != "loadFailed":
            # The track played, however briefly, so the run of failures ended.
            self._failures.on_played(player.guild.id)
        await self.persist_queue(player)

        # Nothing follows this track, so no track_start will arrive to replace
        # the panel. Left alone it advertises a finished track forever, with
        # buttons that can only answer "nothing is playing" - which is what
        # skipping the last track used to do.
        guild_id = player.guild.id
        if guild_id in self._stopping:
            return  # /stop already tears the panel down
        if payload.reason == "loadFailed" and guild_id in self._radio_resume:
            # A radio pick failed for good; the exception handler left the
            # moving on to this end, as AutoPlay does for a queue.
            self._radio_resume.discard(guild_id)
        elif payload.reason not in QUEUE_ENDING_REASONS:
            # "loadFailed" means the track could not be played, and
            # on_wavelink_track_exception has already dealt with it: either a
            # retry is queued or the channel was told. "replaced" and "cleanup"
            # are not endings at all.
            return
        if player.playing or not player.queue.is_empty:
            return
        if await self.radio_next(player, payload.track):
            return
        if self.radio_on(guild_id) and player.queue.mode is wavelink.QueueMode.normal:
            await self.retire_panel(
                guild_id,
                "📻 Радио не нашло похожих треков",
                note="Включите трек через `/play` — радио продолжит от него.",
            )
            return
        await self.retire_panel(guild_id, "🏁 Очередь закончилась")

    async def _report_playback_problem(
        self, player: wavelink.Player | None, track: wavelink.Playable, text: str
    ) -> None:
        """Tell the channel a track could not be played.

        The notice removes itself after FAILURE_NOTICE_TTL; the panel shows
        the lasting state (the next track, or idle when nothing follows).
        """
        if player is None or player.guild is None:
            return
        channel_id = self.home_channels.get(player.guild.id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.abc.Messageable):
            return
        view = PanelView(timeout=None)
        view.add_item(
            make_panel(
                title="⚠️ Трек не удалось воспроизвести",
                body=f"**{track.title}**\n{text}",
                accent=0xED4245,
            )
        )
        try:
            await channel.send(view=view, delete_after=FAILURE_NOTICE_TTL)
        except discord.HTTPException:
            logger.debug("Could not report the playback problem", exc_info=True)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        """A track failed to start or died mid-stream.

        Lavalink follows this event with ``TrackEnd(loadFailed)``, and on that
        event wavelink's AutoPlay plays whatever ``queue.get()`` returns. So a
        retry is arranged by putting the track back at the head of the queue
        and letting AutoPlay start it - not by calling ``player.play`` here.
        Playing it directly raced AutoPlay: the ``loadFailed`` end then cleared
        ``player.current`` under the running retry, so every button answered
        "nothing is playing" while music played, and with a queue behind it
        AutoPlay started the next track on top of the retry.

        Everything up to ``_steer_autoplay`` must stay free of ``await``: this
        listener is scheduled before the AutoPlay task for the end event, and
        only its synchronous part is guaranteed to run first.
        """
        player = payload.player
        track = payload.track
        exception = payload.exception or {}
        message = exception.get("message") or exception.get("cause") or ""
        info = classify(message)
        if player is None or player.guild is None:
            logger.warning("Track %r failed: %s", track.title, info.summary)
            return
        guild_id = player.guild.id
        if guild_id in self._stopping:
            return  # /stop is tearing this down; stay silent

        position = max(player.position, self._positions.pop(guild_id, 0))
        decision = self._failures.on_failure(guild_id, self._track_key(track), info, position)
        self._steer_autoplay(player, track, decision)
        # Still synchronous: the end handler for this failure may run as soon
        # as this listener first awaits, and must find the mark.
        radio_continues = (
            decision.verdict is Verdict.GIVE_UP
            and guild_id in self._radio
            and player.queue.is_empty
            and player.queue.mode is wavelink.QueueMode.normal
        )
        if radio_continues:
            self._radio_resume.add(guild_id)

        if decision.verdict is Verdict.RETRY:
            logger.info(
                "Track %r failed, retrying (%d of %d): %s",
                track.title,
                decision.attempt,
                MAX_PLAY_RETRIES,
                info.summary,
            )
            return
        if decision.verdict is Verdict.SILENT:
            return

        logger.warning(
            "Track %r could not be played after %d attempt(s): %s",
            track.title,
            decision.attempt,
            info.summary,
        )
        if message.strip().endswith(CIPHER_FAILURE_SIGNATURE + ", available types:"):
            logger.error(
                "YouTube returned no playable format from any client. If this "
                "happens for every track, the yt-cipher service is unreachable - "
                "check `docker compose ps` and plugins.youtube.remoteCipher."
            )
        if info.needs_login:
            logger.warning(
                "YouTube asked for a signed-in session. See YOUTUBE_OAUTH in "
                ".env.example for how to give Lavalink one."
            )

        if info.needs_login:
            reason = (
                "YouTube не отдал это видео без входа в аккаунт "
                "(проверка «подтвердите, что вы не бот»)."
            )
        else:
            reason = "Источник не отдал аудиопоток."
        if decision.verdict is Verdict.HALT:
            text = (
                f"{reason}\nЭто уже несколько треков подряд, поэтому очередь "
                "приостановлена. `/skip` — попробовать следующий трек."
            )
        elif player.queue.is_empty and not radio_continues:
            text = f"{reason} Попробуйте другую версию трека."
        else:
            text = f"{reason} Играю следующий трек."
        await self._report_playback_problem(player, track, text)
        # With a next track, its track_start replaces the panel. Without one
        # nothing would, and the panel would go on advertising a dead track.
        if decision.verdict is Verdict.HALT:
            await self.retire_panel(
                guild_id,
                "⏸️ Очередь приостановлена",
                note="Несколько треков подряд не воспроизвелись. `/skip` — следующий.",
            )
        elif player.queue.is_empty and not radio_continues:
            await self.retire_panel(guild_id, f"⚠️ Не удалось воспроизвести «{plain(track.title)}»")

    def _steer_autoplay(
        self, player: wavelink.Player, track: wavelink.Playable, decision: Decision
    ) -> None:
        """Arrange what wavelink's AutoPlay does on the ``loadFailed`` end.

        Synchronous on purpose - see ``on_wavelink_track_exception``.
        """
        queue = player.queue
        key = self._track_key(track)
        # The failed attempt was recorded in history when it was played. Left
        # there, "repeat queue" would replay a dead track every cycle, and each
        # retry would add another copy.
        history = queue.history
        if history is not None:
            for index in range(len(history) - 1, -1, -1):
                if self._track_key(history[index]) == key:
                    history.delete(index)
                    break

        if decision.verdict is Verdict.RETRY:
            # In "repeat track" mode queue.get() already returns this track.
            if queue.mode is not wavelink.QueueMode.loop:
                queue.put_at(0, track)
            _set_autoplay_errors(player, 0)
            return
        if decision.verdict is Verdict.SILENT:
            return
        if queue.mode is wavelink.QueueMode.loop:
            # Repeating a track that cannot play would retry it forever.
            queue.mode = wavelink.QueueMode.normal
        _set_autoplay_errors(
            player,
            WAVELINK_AUTOPLAY_ERROR_LIMIT if decision.verdict is Verdict.HALT else 0,
        )

    @staticmethod
    def _track_key(track: wavelink.Playable) -> str:
        """Stable identity for a track, used to count attempts against it."""
        return track.identifier or track.uri or track.title

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        """Lavalink received no audio for `threshold` ms; skip rather than hang."""
        logger.warning("Track stuck for %r after %d ms", payload.track.title, payload.threshold)
        await self._report_playback_problem(
            payload.player, payload.track, "Поток завис — пропускаю."
        )
        if payload.player is not None:
            with contextlib.suppress(wavelink.LavalinkException, wavelink.NodeException):
                await payload.player.skip(force=True)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Leave when idle for ``inactive_timeout`` seconds."""
        if player.guild is None:
            return
        guild_id = player.guild.id
        await self.retire_panel(guild_id, "💤 Отключился из-за бездействия")
        await player.disconnect()
        await self.bot.db.clear_session(guild_id)
        self._forget_guild(guild_id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # The bot itself was disconnected (kicked / moved out).
        if (
            self.bot.user is not None
            and member.id == self.bot.user.id
            and before.channel is not None
            and after.channel is None
        ):
            await self.retire_panel(member.guild.id, "👋 Бота отключили от голосового канала")
            await self.bot.db.clear_session(member.guild.id)
            self._forget_guild(member.guild.id)
            return

        # A user moved: if the bot is now alone, leave.
        if before.channel == after.channel:
            return
        player = player_of(member.guild)
        if player is None or player.channel is None:
            return
        if not any(not m.bot for m in player.channel.members):
            guild_id = member.guild.id
            await self.retire_panel(guild_id, "👋 Все вышли из голосового канала")
            await player.disconnect()
            await self.bot.db.clear_session(guild_id)
            self._forget_guild(guild_id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self._forget_guild(guild.id)

    # ------------------------------------------------------------------ #
    #  Restart recovery
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        if self._restored:
            return
        self._restored = True
        await self._restore_sessions()

    async def _remove_stale_panels(self) -> None:
        """Delete panels a previous process left behind.

        Their buttons still work (the view is persistent) but they show a
        track from before the restart; a restored session posts a fresh one.
        """
        try:
            panels = await self.bot.db.take_now_panels()
        except sqlite3.Error:
            logger.exception("Failed to load the previous now-playing panels")
            return
        for _guild_id, channel_id, message_id in panels:
            message = self.bot.get_partial_messageable(channel_id).get_partial_message(message_id)
            with contextlib.suppress(discord.HTTPException):
                await message.delete()

    async def _restore_sessions(self) -> None:
        await self._remove_stale_panels()
        try:
            sessions = await self.bot.db.load_sessions()
        except sqlite3.Error:
            logger.exception("Failed to load sessions")
            return
        for session in sessions:
            try:
                await self._restore_one(session)
            except Exception:
                logger.exception("Failed to restore guild %s", session.guild_id)

    async def _restore_one(self, session: PlayerSession) -> None:
        guild = self.bot.get_guild(session.guild_id)
        channel = guild.get_channel(session.voice_channel_id) if guild else None
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await self.bot.db.clear_session(session.guild_id)
            return
        # Only restore if real users are still listening.
        if not any(not m.bot for m in channel.members):
            await self.bot.db.clear_session(session.guild_id)
            return
        saved = await self.bot.db.load_queue(session.guild_id)
        if not saved:
            await self.bot.db.clear_session(session.guild_id)
            return

        player = await connect_and_configure(channel, self.bot)
        if session.text_channel_id:
            self.home_channels[session.guild_id] = session.text_channel_id

        for item in saved:
            try:
                found = await wavelink.Playable.search(item.uri)
            except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
                logger.warning(
                    "Skipping unresolvable track %r for guild %s",
                    item.uri,
                    session.guild_id,
                )
                continue
            if isinstance(found, wavelink.Playlist):
                found = found.tracks
            if not found:
                continue
            track = found[0]
            if item.requester:
                track.extras = {"requester": item.requester, "avatar": item.avatar}
            player.queue.put(track)

        await self.maybe_start(player)
        logger.info("Restored %d tracks for guild %s", len(player.queue) + 1, session.guild_id)


async def setup(bot: MusicBot) -> None:
    cog = Music(bot)
    await bot.add_cog(cog)
    # Routes presses on panels posted before this process started.
    bot.add_view(NowPlayingView(cog))
