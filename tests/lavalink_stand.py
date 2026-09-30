"""A scripted Lavalink behind the real wavelink machinery.

The player bugs that reached production all lived in the space *between*
this bot and wavelink: which of them reacts to an event first, and what
wavelink's own AutoPlay does with ``player.current`` and the queue when a track
fails. A ``MagicMock`` player has none of that behaviour, so tests built on one
passed while the bot froze its queue and answered every button with "nothing
is playing".

Here only Lavalink itself is fake. Events are delivered as JSON through a real
:class:`wavelink.websocket.Websocket` read loop, to a real
:class:`wavelink.Player` with a real :class:`wavelink.Queue`, so wavelink
dispatches listeners and schedules its AutoPlay exactly as it does in
production.

What the fake reproduces is Lavalink's documented event order: a track that
cannot be played produces ``TrackStartEvent``, then ``TrackExceptionEvent``,
then ``TrackEndEvent`` with reason ``loadFailed``; replacing a loaded track ends
it with ``replaced``; stopping ends it with ``stopped``.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import discord
import wavelink
from wavelink.websocket import Websocket

from tests.interaction_harness import make_member

#: The failure from the production log this stand was built to reproduce:
#: every client refused "АлСми - Базовый минимум", with a mix of transient
#: (SABR, 403) and sign-in reasons. Stack frames trimmed.
REAL_ALL_CLIENTS_FAILED = (
    "(yts.version: 1.18.2) All clients failed to load the item.\n\n"
    "Client [TVHTML5] failed: The page needs to be reloaded.\n"
    "    at dev.lavalink.youtube.clients.skeleton.Client.getPlayabilityStatus(Client.java:77)\n\n"
    "Client [ANDROID_VR] failed: This video requires login.\n"
    "    at dev.lavalink.youtube.clients.skeleton.Client.getPlayabilityStatus(Client.java:94)\n\n"
    "Client [ANDROID_MUSIC] failed: This video requires login.\n\n"
    "Client [IOS] failed: Invalid status code for player api response: 400\n\n"
    "Client [TVHTML5_SIMPLY] failed: Sign in to confirm you’re not a bot\n\n"
    "Client [MWEB] failed: Not success status code: 403\n\n"
    "Client [WEB] failed: No supported audio streams available, available types: \n\n"
    "Client [WEB_EMBEDDED_PLAYER] failed: Video player configuration error\n"
)

VIDEO_UNAVAILABLE = (
    "(yts.version: 1.18.2) All clients failed to load the item.\n\n"
    "Client [TVHTML5] failed: This video is unavailable\n\n"
    "Client [WEB] failed: Video unavailable\n"
)


def track_data(title: str, *, length: int = 180_000) -> dict[str, Any]:
    return {
        "encoded": f"enc-{title}",
        "info": {
            "identifier": title,
            "isSeekable": True,
            "author": "artist",
            "length": length,
            "isStream": False,
            "position": 0,
            "title": title,
            "uri": f"https://example/{title}",
            "sourceName": "youtube",
            "artworkUrl": None,
            "isrc": None,
        },
        "pluginInfo": {},
        "userData": {},
    }


class _Socket:
    """The part of ``aiohttp.ClientWebSocketResponse`` the read loop uses.

    ``separate=False`` hands over buffered messages without yielding, as
    aiohttp does when several frames arrived in one read: wavelink then
    processes Lavalink's exception *and* end event before any listener runs.
    ``separate=True`` lets the loop run between messages, as when they arrive
    in separate reads. Production sees both, so the tests run in both.
    """

    def __init__(self, *, separate: bool) -> None:
        self.inbox: asyncio.Queue[aiohttp.WSMessage] = asyncio.Queue()
        self.closed = False
        self.separate = separate

    async def receive(self) -> aiohttp.WSMessage:
        if self.separate:
            await asyncio.sleep(0.001)
        return await self.inbox.get()

    def push(self, payload: dict[str, Any]) -> None:
        self.inbox.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(payload), None))


@dataclass
class _GuildState:
    loaded: str | None = None  # encoded track Lavalink is playing
    paused: bool = False
    seeks: list[int] = field(default_factory=list)


class FakeLavalink:
    """Scripted Lavalink node.

    ``script[title]`` is a list of outcomes consumed one per play of that
    track: ``"ok"`` (plays until :meth:`finish`) or an exception message.
    Unscripted plays succeed.
    """

    def __init__(self, client: discord.Client, *, separate: bool = False) -> None:
        self.client = client
        self.status = wavelink.NodeStatus.CONNECTED
        self.session_id = "fake"
        self.players: dict[int, wavelink.Player] = {}
        self._inactive_channel_tokens = None
        self._inactive_player_timeout = None
        self.script: dict[str, deque[str]] = defaultdict(deque)
        self.plays: list[str] = []
        self.guilds: dict[int, _GuildState] = defaultdict(_GuildState)
        self._tracks: dict[str, dict[str, Any]] = {}
        self._socket = _Socket(separate=separate)
        self._ws = Websocket(node=self)  # type: ignore[arg-type]
        self._ws.socket = self._socket  # type: ignore[assignment]
        self._reader: asyncio.Task[None] | None = None
        self._ignore: set[asyncio.Task[Any]] = set()

    # -- the Node surface wavelink's Player and Websocket touch -------------
    def get_player(self, guild_id: int) -> wavelink.Player | None:
        return self.players.get(int(guild_id))

    async def _update_player(
        self, guild_id: int, /, *, data: dict[str, Any], replace: bool = False
    ) -> dict[str, Any]:
        # A real REST call always suspends. Answering synchronously would hide
        # every race between the caller and the websocket events.
        await asyncio.sleep(0)
        state = self.guilds[guild_id]
        if "paused" in data and "track" not in data:
            state.paused = bool(data["paused"])
        if "position" in data and "track" not in data:
            state.seeks.append(int(data["position"]))
        if "track" not in data:
            return {}
        encoded = data["track"].get("encoded")
        if encoded is None:  # skip / stop
            if state.loaded is not None:
                self._end(guild_id, state.loaded, "stopped")
            return {}
        if state.loaded is not None:
            if not replace:
                return {}
            self._end(guild_id, state.loaded, "replaced")
        self._load(guild_id, encoded)
        return {}

    # -- scripting -----------------------------------------------------------
    def register(self, track: wavelink.Playable) -> wavelink.Playable:
        self._tracks[track.encoded] = track_data(track.title, length=track.length)
        return track

    def track(self, title: str, *, length: int = 180_000) -> wavelink.Playable:
        data = track_data(title, length=length)
        self._tracks[data["encoded"]] = data
        return wavelink.Playable(data)

    def fail(self, title: str, times: int, message: str = REAL_ALL_CLIENTS_FAILED) -> None:
        self.script[title].extend([message] * times)

    def finish(self, guild_id: int) -> None:
        """The loaded track reached its end."""
        state = self.guilds[guild_id]
        if state.loaded is not None:
            self._end(guild_id, state.loaded, "finished")

    def fail_mid_stream(self, guild_id: int, position: int, message: str) -> None:
        """The loaded track broke off after ``position`` ms of audio."""
        state = self.guilds[guild_id]
        assert state.loaded is not None
        self._socket.push(
            {
                "op": "playerUpdate",
                "guildId": str(guild_id),
                "state": {"time": 0, "position": position, "connected": True, "ping": 1},
            }
        )
        self._exception(guild_id, state.loaded, message)
        self._end(guild_id, state.loaded, "loadFailed")

    def now(self, guild_id: int) -> str | None:
        loaded = self.guilds[guild_id].loaded
        return self._tracks[loaded]["info"]["title"] if loaded else None

    # -- internals -----------------------------------------------------------
    def _load(self, guild_id: int, encoded: str) -> None:
        data = self._tracks[encoded]
        title = data["info"]["title"]
        self.plays.append(title)
        state = self.guilds[guild_id]
        state.loaded = encoded
        self._event(guild_id, "TrackStartEvent", encoded)
        outcomes = self.script[title]
        outcome = outcomes.popleft() if outcomes else "ok"
        if outcome != "ok":
            self._exception(guild_id, encoded, outcome)
            self._end(guild_id, encoded, "loadFailed")

    def _exception(self, guild_id: int, encoded: str, message: str) -> None:
        self._event(
            guild_id,
            "TrackExceptionEvent",
            encoded,
            exception={"message": message, "severity": "suspicious", "cause": message},
        )

    def _end(self, guild_id: int, encoded: str, reason: str) -> None:
        state = self.guilds[guild_id]
        if state.loaded == encoded:
            state.loaded = None
        self._event(guild_id, "TrackEndEvent", encoded, reason=reason)

    def _event(self, guild_id: int, kind: str, encoded: str, **extra: Any) -> None:
        self._socket.push(
            {
                "op": "event",
                "type": kind,
                "guildId": str(guild_id),
                "track": self._tracks[encoded],
                **extra,
            }
        )

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.baseline()
        self._reader = asyncio.create_task(self._ws.keep_alive())

    async def stop(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with _suppress_cancel():
                await self._reader

    def baseline(self) -> None:
        """Tasks alive now belong to the test runner, not to event handling."""
        self._ignore = set(asyncio.all_tasks())

    async def settle(self, within: float = 5.0) -> None:
        """Run the loop until every event has been delivered and handled.

        Waits in real time rather than a fixed number of loop turns: the
        listeners write to SQLite through aiosqlite's worker thread, and
        those results arrive whenever the thread gets to them.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + within
        me = asyncio.current_task()
        busy: list[asyncio.Task[Any]] = []
        quiet_turns = 0
        while loop.time() < deadline:
            await asyncio.sleep(0.001)
            if self._reader is not None and self._reader.done():
                # The read loop died; its exception is the real failure.
                self._reader.result()
                raise AssertionError("the websocket read loop stopped")
            busy = [
                t
                for t in asyncio.all_tasks()
                if t is not me and t is not self._reader and t not in self._ignore and not t.done()
            ]
            if self._socket.inbox.empty() and not busy:
                quiet_turns += 1
                if quiet_turns >= 3:  # nothing new queued for a few turns
                    return
            else:
                quiet_turns = 0
        raise AssertionError(
            "events did not settle - something is looping: "
            + ", ".join(repr(t.get_coro()) for t in busy)
        )


class _suppress_cancel:
    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, *_: Any) -> bool:
        return kind is asyncio.CancelledError


def make_real_player(bot: discord.Client, lavalink: FakeLavalink, guild: Any) -> wavelink.Player:
    """A genuine wavelink Player, connected, in a channel with one listener."""
    voice = MagicMock(spec=discord.VoiceChannel)
    voice.id = 77
    voice.guild = guild
    voice.members = [make_member(5, guild=guild)]
    player = wavelink.Player(bot, voice, nodes=[lavalink])  # type: ignore[list-item]
    player._guild = guild
    player._connected = True
    player.autoplay = wavelink.AutoPlayMode.partial
    guild.voice_client = player
    lavalink.players[guild.id] = player
    return player
