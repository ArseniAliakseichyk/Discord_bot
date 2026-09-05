"""The player across track changes, teardown and restart.

Track transitions are where this bot has historically gone wrong: now-playing
messages piling up, a saved queue resurrecting itself after /stop, sessions
surviving a kick, per-guild bookkeeping never released. Each of those is a
sequence of events rather than a single call, so they are driven here through
the real listeners with a player double.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import wavelink

from core.bot import INITIAL_EXTENSIONS, MusicBot
from core.db import PlayerSession
from tests.interaction_harness import (
    make_channel,
    make_guild,
    make_member,
    make_player,
    make_track,
)


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "player.db")))
    await instance.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await instance.load_extension(extension)
    try:
        yield instance
    finally:
        await instance.db.close()


class SentMessage:
    """A now-playing message that records whether it was edited or deleted."""

    _counter = 0

    def __init__(self) -> None:
        SentMessage._counter += 1
        self.id = SentMessage._counter
        self.deleted = False
        self.edits = 0

    async def edit(self, **kwargs):
        self.edits += 1
        return self

    async def delete(self) -> None:
        if self.deleted:
            raise discord.NotFound(MagicMock(status=404), "already deleted")
        self.deleted = True


def make_home_channel(channel_id: int = 55):
    """The text channel the bot posts now-playing panels into.

    Built on a TextChannel spec so it satisfies the
    ``isinstance(channel, discord.abc.Messageable)`` guard in the listeners;
    a plain object makes them return early and the test proves nothing.
    """
    channel = make_channel(channel_id)
    channel.sent = []
    channel.texts = []

    async def send(content: str | None = None, **kwargs):
        if content is not None:
            channel.texts.append(content)
        message = SentMessage()
        channel.sent.append(message)
        return message

    channel.send = AsyncMock(side_effect=send)
    return channel


def setup_guild(bot: MusicBot):
    """A guild with a connected player and a registered home channel."""
    guild = make_guild()
    player = make_player(guild)
    music = bot.get_cog("Music")
    home = make_home_channel()
    music.home_channels[guild.id] = home.id
    bot.get_channel = lambda cid: home if cid == home.id else None  # type: ignore[method-assign]
    return music, guild, player, home


def as_bot_user(bot: MusicBot, user_id: int) -> None:
    """Give the bot an identity.

    ``Client.user`` is a read-only property backed by the connection state, so
    the listeners' "was this me?" check is satisfied by setting it there.
    """
    bot._connection.user = MagicMock(id=user_id)  # type: ignore[attr-defined]


def start_payload(player, track) -> MagicMock:
    payload = MagicMock(spec=wavelink.TrackStartEventPayload)
    payload.player = player
    payload.track = track
    return payload


def end_payload(player, track, reason: str = "finished") -> MagicMock:
    """Lavalink always sends a reason; the handler branches on it."""
    payload = MagicMock(spec=wavelink.TrackEndEventPayload)
    payload.player = player
    payload.track = track
    payload.reason = reason
    return payload


# --------------------------------------------------------------------------- #
#  Track changes
# --------------------------------------------------------------------------- #
class TestTrackChanges:
    async def test_first_track_posts_one_panel(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        assert len(home.sent) == 1
        assert music.now_messages[guild.id] is home.sent[0]

    async def test_next_track_replaces_the_panel_instead_of_stacking(self, bot) -> None:
        """Without the delete, every track leaves a dead panel behind."""
        music, guild, player, home = setup_guild(bot)
        for title in ("a", "b", "c"):
            await music.on_wavelink_track_start(start_payload(player, make_track(title)))

        assert len(home.sent) == 3
        assert [m.deleted for m in home.sent] == [True, True, False]
        assert music.now_messages[guild.id] is home.sent[-1]

    async def test_a_manually_deleted_panel_does_not_break_the_next_track(
        self, bot
    ) -> None:
        """Someone deletes the message; the next transition must still work."""
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        home.sent[0].deleted = True  # deleted out from under us

        await music.on_wavelink_track_start(start_payload(player, make_track("b")))
        assert len(home.sent) == 2
        assert music.now_messages[guild.id] is home.sent[1]

    async def test_track_start_persists_the_queue(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.queue.put(make_track("next"))
        await music.on_wavelink_track_start(start_payload(player, make_track("now")))

        sessions = await bot.db.load_sessions()
        assert [s.guild_id for s in sessions] == [guild.id]
        saved = await bot.db.load_queue(guild.id)
        assert [t.uri for t in saved] == [
            player.current.uri,
            "https://example/next",
        ]

    async def test_track_end_persists_the_remaining_queue(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.queue.put(make_track("b"))
        await music.on_wavelink_track_end(end_payload(player, make_track("a")))
        saved = await bot.db.load_queue(guild.id)
        assert [t.uri for t in saved][-1] == "https://example/b"

    async def test_queue_order_survives_persistence(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        for title in ("one", "two", "three"):
            player.queue.put(make_track(title))
        await music.persist_queue(player)
        saved = await bot.db.load_queue(guild.id)
        assert [t.uri for t in saved[1:]] == [
            "https://example/one",
            "https://example/two",
            "https://example/three",
        ]

    async def test_requester_metadata_round_trips(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        track = make_track("x")
        track.extras = {"requester": "Аня", "avatar": "https://cdn/a.png"}
        player.queue.put(track)
        await music.persist_queue(player)

        saved = await bot.db.load_queue(guild.id)
        restored = next(t for t in saved if t.uri == "https://example/x")
        assert (restored.requester, restored.avatar) == ("Аня", "https://cdn/a.png")

    async def test_rapid_track_changes_leave_exactly_one_live_panel(self, bot) -> None:
        """Skipping quickly used to race the delete and strand panels."""
        music, guild, player, home = setup_guild(bot)
        await asyncio.gather(
            *(
                music.on_wavelink_track_start(start_payload(player, make_track(t)))
                for t in ("a", "b", "c", "d")
            )
        )
        live = [m for m in home.sent if not m.deleted]
        assert len(live) == 1, f"{len(live)} panels left alive: {[m.id for m in live]}"
        assert music.now_messages[guild.id] in live


# --------------------------------------------------------------------------- #
#  Stop during a track change
# --------------------------------------------------------------------------- #
class TestStopRace:
    async def test_stop_does_not_leave_a_resurrected_session(self, bot) -> None:
        """The forced skip inside stop_player produces a track_end event.

        wavelink dispatches that event as its own task, so it lands while
        stop_player is still awaiting - after the queue was cleared but around
        the session delete. Without the _stopping guard the listener re-saves
        the very session the stop is removing, and the queue returns after a
        restart. Scheduling the event rather than awaiting it inline is what
        makes this reproduce the real ordering.
        """
        music, guild, player, home = setup_guild(bot)
        player.queue.put(make_track("a"))
        await music.persist_queue(player)
        assert await bot.db.load_sessions()

        pending: list[asyncio.Task[None]] = []

        async def skip(*_args, **_kwargs):
            pending.append(
                asyncio.create_task(
                    music.on_wavelink_track_end(end_payload(player, make_track("a")))
                )
            )

        player.skip = AsyncMock(side_effect=skip)
        await music.stop_player(player)
        await asyncio.gather(*pending)

        assert await bot.db.load_sessions() == [], "the session came back after /stop"
        assert await bot.db.load_queue(guild.id) == []

    async def test_stop_clears_queues_and_the_panel(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        player.queue.put(make_track("b"))
        player.auto_queue.put(make_track("c"))

        await music.stop_player(player)

        assert player.queue.is_empty and player.auto_queue.is_empty
        assert home.sent[0].deleted
        assert guild.id not in music.now_messages

    async def test_stop_releases_the_stopping_flag(self, bot) -> None:
        """A stuck flag would silently disable persistence for that guild."""
        music, guild, player, home = setup_guild(bot)
        player.skip = AsyncMock(side_effect=RuntimeError("lavalink is down"))
        with pytest.raises(RuntimeError):
            await music.stop_player(player)
        assert guild.id not in music._stopping

        player.skip = AsyncMock()
        player.queue.put(make_track("a"))
        await music.persist_queue(player)
        assert await bot.db.load_sessions(), "persistence stayed disabled after a failure"


# --------------------------------------------------------------------------- #
#  Leaving the channel
# --------------------------------------------------------------------------- #
class TestDisconnects:
    async def test_inactivity_disconnects_and_cleans_up(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        await music.persist_queue(player)

        await music.on_wavelink_inactive_player(player)

        player.disconnect.assert_awaited_once()
        assert await bot.db.load_sessions() == []
        assert guild.id not in music.home_channels
        assert guild.id not in music.now_messages
        assert home.sent[0].deleted
        assert any("бездействия" in t for t in home.texts)

    async def test_being_kicked_from_voice_cleans_up(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        await music.persist_queue(player)

        bot_member = make_member(999, guild=guild, bot=True)
        as_bot_user(bot, 999)
        before = MagicMock(spec=discord.VoiceState)
        before.channel = make_channel(77, guild=guild)
        after = MagicMock(spec=discord.VoiceState)
        after.channel = None

        await music.on_voice_state_update(bot_member, before, after)

        assert await bot.db.load_sessions() == []
        assert guild.id not in music.home_channels
        assert home.sent[0].deleted

    async def test_last_human_leaving_disconnects_the_bot(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.persist_queue(player)
        as_bot_user(bot, 999)

        only_bots = make_channel(77, guild=guild)
        only_bots.members = [make_member(999, guild=guild, bot=True)]
        player.channel = only_bots

        human = make_member(1, guild=guild)
        before = MagicMock(spec=discord.VoiceState)
        before.channel = only_bots
        after = MagicMock(spec=discord.VoiceState)
        after.channel = None

        await music.on_voice_state_update(human, before, after)

        player.disconnect.assert_awaited_once()
        assert await bot.db.load_sessions() == []

    async def test_bot_stays_while_a_human_remains(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        as_bot_user(bot, 999)

        channel = make_channel(77, guild=guild)
        channel.members = [
            make_member(999, guild=guild, bot=True),
            make_member(2, guild=guild),
        ]
        player.channel = channel

        before = MagicMock(spec=discord.VoiceState)
        before.channel = channel
        after = MagicMock(spec=discord.VoiceState)
        after.channel = None

        await music.on_voice_state_update(make_member(1, guild=guild), before, after)
        player.disconnect.assert_not_awaited()

    async def test_leaving_a_guild_releases_its_bookkeeping(self, bot) -> None:
        """These dicts are keyed by guild and never expired otherwise."""
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        assert guild.id in music.home_channels and guild.id in music.now_messages

        await music.on_guild_remove(guild)
        assert guild.id not in music.home_channels
        assert guild.id not in music.now_messages
        assert guild.id not in music._stopping


# --------------------------------------------------------------------------- #
#  Restart recovery
# --------------------------------------------------------------------------- #
class TestRestore:
    async def test_session_is_dropped_when_the_channel_is_gone(self, bot) -> None:
        music = bot.get_cog("Music")
        await bot.db.save_session(5, 77, 55, [])
        bot.get_guild = lambda _id: None  # type: ignore[method-assign]

        await music._restore_one(PlayerSession(5, 77, 55))
        assert await bot.db.load_sessions() == []

    async def test_session_is_dropped_when_nobody_is_listening(self, bot) -> None:
        music = bot.get_cog("Music")
        guild = make_guild()
        empty = MagicMock(spec=discord.VoiceChannel)
        empty.members = [make_member(999, guild=guild, bot=True)]
        guild.get_channel = lambda _id: empty
        bot.get_guild = lambda _id: guild  # type: ignore[method-assign]

        from core.db import SavedTrack

        await bot.db.save_session(guild.id, 77, 55, [SavedTrack(uri="https://x/a")])
        await music._restore_one(PlayerSession(guild.id, 77, 55))

        assert await bot.db.load_sessions() == []

    async def test_restore_runs_once_per_process(self, bot) -> None:
        """on_wavelink_node_ready fires again on every reconnect."""
        music = bot.get_cog("Music")
        calls = 0

        async def counting():
            nonlocal calls
            calls += 1

        music._restore_sessions = counting
        payload = MagicMock(spec=wavelink.NodeReadyEventPayload)
        await music.on_wavelink_node_ready(payload)
        await music.on_wavelink_node_ready(payload)
        assert calls == 1, "sessions were restored twice after a reconnect"

    async def test_one_bad_guild_does_not_stop_the_rest(self, bot) -> None:
        music = bot.get_cog("Music")
        await bot.db.save_session(1, 77, 55, [])
        await bot.db.save_session(2, 78, 56, [])
        seen: list[int] = []

        async def restore(session):
            seen.append(session.guild_id)
            if session.guild_id == 1:
                raise RuntimeError("boom")

        music._restore_one = restore
        await music._restore_sessions()
        assert sorted(seen) == [1, 2]


# --------------------------------------------------------------------------- #
#  Starting playback
# --------------------------------------------------------------------------- #
class TestMaybeStart:
    async def test_starts_when_idle_with_a_queue(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.playing = False
        player.play = AsyncMock()
        player.queue.put(make_track("a"))

        await music.maybe_start(player)
        player.play.assert_awaited_once()

    async def test_does_not_restart_while_already_playing(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.playing = True
        player.play = AsyncMock()
        player.queue.put(make_track("a"))

        await music.maybe_start(player)
        player.play.assert_not_awaited()

    async def test_does_nothing_on_an_empty_queue(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.playing = False
        player.play = AsyncMock()

        await music.maybe_start(player)
        player.play.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  Playback failures
# --------------------------------------------------------------------------- #
class TestPlaybackFailures:
    """A track that cannot play must say so, not leave a stale panel.

    This is the failure people actually hit: the YouTube source cannot obtain a
    stream, Lavalink raises a TrackException, and before this the only trace was
    a Java stack trace in the container log.
    """

    def _exception(self, player, track, message="No supported audio streams"):
        payload = MagicMock(spec=wavelink.TrackExceptionEventPayload)
        payload.player = player
        payload.track = track
        payload.exception = MagicMock(message=message)
        return payload

    def _stuck(self, player, track, threshold=10_000):
        payload = MagicMock(spec=wavelink.TrackStuckEventPayload)
        payload.player = player
        payload.track = track
        payload.threshold = threshold
        return payload

    async def test_exception_tells_the_channel_once_retries_run_out(self, bot) -> None:
        """The first failures are retried silently; the last one is reported."""
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        home.sent.clear()
        player.play = AsyncMock()

        for _ in range(MAX_PLAY_RETRIES + 1):
            await music.on_wavelink_track_exception(
                self._exception(player, make_track("a"))
            )
        assert home.sent, "the failure was never reported to the channel"

    async def test_exception_clears_the_stale_panel(self, bot) -> None:
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        panel = home.sent[0]
        player.play = AsyncMock()

        for _ in range(MAX_PLAY_RETRIES + 1):
            await music.on_wavelink_track_exception(
                self._exception(player, make_track("a"))
            )
        assert panel.deleted, "the panel kept advertising a track that never played"
        assert guild.id not in music.now_messages

    async def test_exception_without_a_player_is_ignored(self, bot) -> None:
        music = bot.get_cog("Music")
        await music.on_wavelink_track_exception(
            self._exception(None, make_track("a"))
        )

    async def test_stuck_skips_the_track(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_stuck(self._stuck(player, make_track("a")))
        player.skip.assert_awaited_once_with(force=True)

    async def test_stuck_survives_a_failing_skip(self, bot) -> None:
        """Lavalink may already be gone; reporting still has to happen."""
        music, guild, player, home = setup_guild(bot)
        player.skip = AsyncMock(side_effect=wavelink.NodeException("node down"))
        await music.on_wavelink_track_stuck(self._stuck(player, make_track("a")))
        assert home.sent, "the user was told nothing when the skip also failed"

    async def test_the_rest_of_the_queue_is_untouched(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.queue.put(make_track("next"))
        await music.on_wavelink_track_exception(
            self._exception(player, make_track("broken"))
        )
        assert [t.title for t in player.queue] == ["next"]


# --------------------------------------------------------------------------- #
#  End of queue
# --------------------------------------------------------------------------- #
class TestQueueEnd:
    """Skipping the last track used to leave the panel up for good.

    No further track_start arrives to replace it, so the message kept
    advertising a finished track with buttons that could only answer "nothing
    is playing".
    """

    def _end(self, player, track, reason="finished"):
        payload = MagicMock(spec=wavelink.TrackEndEventPayload)
        payload.player = player
        payload.track = track
        payload.reason = reason
        return payload

    async def test_last_track_retires_the_panel(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("only")))
        panel = home.sent[0]

        player.playing = False
        player.current = None
        await music.on_wavelink_track_end(self._end(player, make_track("only")))

        assert panel.deleted, "the finished track's panel was left in the channel"
        assert guild.id not in music.now_messages

    async def test_the_channel_is_told_the_queue_ended(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("only")))
        player.playing = False
        await music.on_wavelink_track_end(self._end(player, make_track("only")))
        assert len(home.sent) == 2, "no closing message was posted"

    async def test_panel_survives_between_tracks(self, bot) -> None:
        """With more queued, track_start replaces the panel; do not pre-empt it."""
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        panel = home.sent[0]
        player.queue.put(make_track("b"))
        player.playing = True

        await music.on_wavelink_track_end(self._end(player, make_track("a")))
        assert not panel.deleted, "the panel was retired while the queue continued"
        assert guild.id in music.now_messages

    async def test_autoplay_queue_also_counts_as_more_to_play(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        panel = home.sent[0]
        player.playing = False
        player.auto_queue.put(make_track("radio"))

        await music.on_wavelink_track_end(self._end(player, make_track("a")))
        assert not panel.deleted, "autoplay had a track queued but the panel was dropped"

    async def test_stop_does_not_post_a_queue_ended_notice(self, bot) -> None:
        """/stop already reports itself; a second message would be noise."""
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        home.sent.clear()

        async def skip(*_a, **_k):
            player.playing = False
            await music.on_wavelink_track_end(self._end(player, make_track("a")))

        player.skip = AsyncMock(side_effect=skip)
        await music.stop_player(player)
        assert not home.sent, "stop_player posted a redundant end-of-queue notice"


class TestNoDuplicateEndNotice:
    """A failed track must produce one message, not two.

    on_wavelink_track_exception already removes the panel and explains the
    failure. Lavalink then sends track_end with reason "loadFailed"; treating
    that as the queue ending posted a second message and had both handlers
    racing for the same panel.
    """

    def _end(self, player, track, reason):
        payload = MagicMock(spec=wavelink.TrackEndEventPayload)
        payload.player = player
        payload.track = track
        payload.reason = reason
        return payload

    def _exception(self, player, track):
        payload = MagicMock(spec=wavelink.TrackExceptionEventPayload)
        payload.player = player
        payload.track = track
        payload.exception = MagicMock(message="No supported audio streams")
        return payload

    async def test_failed_track_reports_once(self, bot) -> None:
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("bad")))
        home.sent.clear()
        player.playing = False
        player.play = AsyncMock()

        for _ in range(MAX_PLAY_RETRIES + 1):
            await music.on_wavelink_track_exception(
                self._exception(player, make_track("bad"))
            )
        await music.on_wavelink_track_end(self._end(player, make_track("bad"), "loadFailed"))

        assert len(home.sent) == 1, (
            f"expected one failure message, got {len(home.sent)} - the queue-ended "
            f"notice fired on top of it"
        )

    @pytest.mark.parametrize("reason", ["replaced", "cleanup", "loadFailed"])
    async def test_non_endings_do_not_announce_the_queue(self, bot, reason) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        home.sent.clear()
        player.playing = False

        await music.on_wavelink_track_end(self._end(player, make_track("a"), reason))
        assert not home.sent, f"reason={reason} should not end the queue"

    @pytest.mark.parametrize("reason", ["finished", "stopped"])
    async def test_real_endings_do_announce(self, bot, reason) -> None:
        music, guild, player, home = setup_guild(bot)
        await music.on_wavelink_track_start(start_payload(player, make_track("a")))
        home.sent.clear()
        player.playing = False

        await music.on_wavelink_track_end(self._end(player, make_track("a"), reason))
        assert len(home.sent) == 1, f"reason={reason} should close the queue out"


class TestRetryOnSourceFailure:
    """YouTube refuses a playable stream at random, so one attempt is a poor
    verdict. Measured on a real track: the same request alternated between
    success and failure, succeeding about one time in six.
    """

    def _exception(self, player, track, message="No supported audio streams available"):
        payload = MagicMock(spec=wavelink.TrackExceptionEventPayload)
        payload.player = player
        payload.track = track
        payload.exception = MagicMock(message=message)
        return payload

    async def test_a_failure_is_retried_rather_than_reported(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("flaky")

        await music.on_wavelink_track_exception(self._exception(player, track))

        player.play.assert_awaited_once_with(track)
        assert not home.sent, "the user was told about a failure that is being retried"

    async def test_it_gives_up_after_the_limit(self, bot) -> None:
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("dead")

        for _ in range(MAX_PLAY_RETRIES + 1):
            await music.on_wavelink_track_exception(self._exception(player, track))

        assert player.play.await_count == MAX_PLAY_RETRIES
        assert home.sent, "after giving up the user must be told"

    async def test_a_different_track_starts_its_own_count(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()

        for name in ("a", "b", "c", "d"):
            await music.on_wavelink_track_exception(
                self._exception(player, make_track(name))
            )
        assert player.play.await_count == 4, "the counter leaked between tracks"

    async def test_retrying_does_not_reset_its_own_budget(self, bot) -> None:
        """The bug that shipped: every attempt logged "attempt 1 of 3" forever.

        player.play() makes Lavalink emit track_start before the track fails
        again. Clearing the counter there made each attempt look like the
        first, so the track retried without end - hammering YouTube and
        redrawing the panel every cycle.
        """
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("flaky")

        # Ten failures, each preceded by the track_start its retry produced.
        for _ in range(10):
            await music.on_wavelink_track_start(start_payload(player, track))
            await music.on_wavelink_track_exception(self._exception(player, track))

        assert player.play.await_count == MAX_PLAY_RETRIES, (
            f"retried {player.play.await_count} times instead of "
            f"{MAX_PLAY_RETRIES} - the counter is being reset"
        )

    async def test_a_finished_track_frees_its_budget(self, bot) -> None:
        """A track that played through can be retried again if replayed."""
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("recovers")

        await music.on_wavelink_track_exception(self._exception(player, track))
        end = MagicMock(spec=wavelink.TrackEndEventPayload)
        end.player, end.track, end.reason = player, track, "finished"
        await music.on_wavelink_track_end(end)
        await music.on_wavelink_track_exception(self._exception(player, track))

        assert player.play.await_count == 2, "the budget was not released"

    async def test_retrying_does_not_redraw_the_panel(self, bot) -> None:
        """Each retry reposting the panel is what made the UI flicker."""
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("flaky")

        await music.on_wavelink_track_start(start_payload(player, track))
        assert len(home.sent) == 1
        home.sent.clear()

        for _ in range(3):
            await music.on_wavelink_track_exception(self._exception(player, track))
            await music.on_wavelink_track_start(start_payload(player, track))

        assert not home.sent, (
            f"{len(home.sent)} extra panels posted while retrying one track"
        )

    async def test_a_different_track_still_gets_its_panel(self, bot) -> None:
        """Suppressing the redraw must not hide genuinely new tracks."""
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()

        await music.on_wavelink_track_exception(
            self._exception(player, make_track("flaky"))
        )
        home.sent.clear()
        await music.on_wavelink_track_start(start_payload(player, make_track("other")))
        assert len(home.sent) == 1, "a new track got no panel"

    async def test_stop_cancels_retrying(self, bot) -> None:
        """A user who pressed stop does not want the track resurrected."""
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        music._stopping.add(guild.id)

        await music.on_wavelink_track_exception(
            self._exception(player, make_track("x"))
        )
        player.play.assert_not_awaited()

    async def test_a_failing_retry_does_not_hide_the_problem(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock(side_effect=wavelink.NodeException("node gone"))

        await music.on_wavelink_track_exception(
            self._exception(player, make_track("x"))
        )
        assert home.sent, "the retry failed and the user was told nothing"

    async def test_the_counter_is_released_with_the_guild(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        await music.on_wavelink_track_exception(
            self._exception(player, make_track("x"))
        )
        assert guild.id in music._play_attempts
        await music.on_guild_remove(guild)
        assert guild.id not in music._play_attempts


class TestFailureIsReportedOnce:
    """One message per dead track, not one per exception.

    After the retry budget ran out, every further exception for the same track
    posted another failure notice, filling the channel and replacing the panel
    each time - the flicker seen in production.
    """

    def _exception(self, player, track):
        payload = MagicMock(spec=wavelink.TrackExceptionEventPayload)
        payload.player = player
        payload.track = track
        payload.exception = MagicMock(message="No supported audio streams available")
        return payload

    async def test_repeated_failures_produce_one_message(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("dead")

        for _ in range(12):
            await music.on_wavelink_track_exception(self._exception(player, track))

        assert len(home.sent) == 1, (
            f"{len(home.sent)} failure notices for one track"
        )

    async def test_retries_stay_within_budget_under_repeat(self, bot) -> None:
        from cogs.music import MAX_PLAY_RETRIES

        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        track = make_track("dead")

        for _ in range(12):
            await music.on_wavelink_track_exception(self._exception(player, track))

        assert player.play.await_count == MAX_PLAY_RETRIES

    async def test_a_new_track_is_reported_on_its_own(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()

        for name in ("first", "second"):
            for _ in range(6):
                await music.on_wavelink_track_exception(
                    self._exception(player, make_track(name))
                )
        assert len(home.sent) == 2, "each dead track deserves its own notice"

    async def test_a_failed_retry_reports_immediately(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock(side_effect=wavelink.NodeException("node gone"))

        await music.on_wavelink_track_exception(
            self._exception(player, make_track("x"))
        )
        assert len(home.sent) == 1

    async def test_stop_suppresses_the_notice(self, bot) -> None:
        music, guild, player, home = setup_guild(bot)
        player.play = AsyncMock()
        music._stopping.add(guild.id)

        await music.on_wavelink_track_exception(
            self._exception(player, make_track("x"))
        )
        assert not home.sent
        player.play.assert_not_awaited()
