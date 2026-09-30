"""Failed tracks against the real wavelink Player, Queue and AutoPlay.

Each test here corresponds to something that went wrong in production:

* a failing track retried forever ("attempt 1 of 3" on repeat);
* every retry reposted the now-playing panel, so the UI flickered;
* after a retry the buttons all answered "nothing is playing" while music
  played, because wavelink cleared ``player.current`` under the retry;
* one bad track froze the rest of the queue, because the retries tripped
  wavelink's three-strikes AutoPlay guard;
* ``/skip`` did nothing once the queue had stalled.

They run on :mod:`tests.lavalink_stand`, where only Lavalink is simulated.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import pytest
import wavelink
from discord import ui

from cogs.music import MAX_PLAY_RETRIES, Music
from core.bot import INITIAL_EXTENSIONS, MusicBot
from tests.interaction_harness import FakeInteraction, drive, make_guild, make_member
from tests.lavalink_stand import (
    VIDEO_UNAVAILABLE,
    FakeLavalink,
    make_real_player,
)
from tests.test_player_lifecycle import make_home_channel
from utils.playback_failures import MAX_CONSECUTIVE_FAILURES


@dataclass
class Stand:
    bot: MusicBot
    music: Music
    lavalink: FakeLavalink
    player: wavelink.Player
    guild: Any
    home: Any

    @property
    def gid(self) -> int:
        return self.guild.id

    async def play(self, *titles: str) -> None:
        """What /play does: enqueue, start if idle."""
        for title in titles:
            self.player.queue.put(self.lavalink.track(title))
        await self.music.maybe_start(self.player)
        await self.lavalink.settle()

    async def finish(self) -> None:
        self.lavalink.finish(self.gid)
        await self.lavalink.settle()

    def panels(self) -> list[Any]:
        """Now-playing panels posted, in order (reports are separate)."""
        return [m for m, v in self._posted() if _is_now_playing(v)]

    def reports(self) -> list[str]:
        return [_text(v) for _, v in self._posted() if "не удалось" in _text(v)]

    def _posted(self) -> list[tuple[Any, Any]]:
        out = []
        for call, message in zip(self.home.send.call_args_list, self.home.sent, strict=True):
            view = call.kwargs.get("view")
            if view is not None:
                out.append((message, view))
        return out

    def live_panel_view(self) -> Any:
        """The view of the panel currently on screen."""
        live = self.music.now_messages.get(self.gid)
        for message, view in self._posted():
            if message is live:
                return view
        raise AssertionError("no live now-playing panel")


def _text(view: Any) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, ui.TextDisplay)
    )


def _is_now_playing(view: Any) -> bool:
    return "Сейчас играет" in _text(view)


@pytest.fixture(params=["batched", "separate"])
async def stand(request, tmp_path, make_settings):
    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "stand.db")))
    # What login() would do: bind the client to the running loop, which
    # dispatch() needs to schedule listeners.
    await bot._async_setup_hook()
    await bot.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await bot.load_extension(extension)
    lavalink = FakeLavalink(bot, separate=request.param == "separate")
    lavalink.start()
    guild = make_guild()
    player = make_real_player(bot, lavalink, guild)
    music = bot.get_cog("Music")
    home = make_home_channel()
    music.home_channels[guild.id] = home.id
    bot.get_channel = lambda cid: home if cid == home.id else None  # type: ignore[method-assign]
    try:
        yield Stand(bot, music, lavalink, player, guild, home)
    finally:
        await lavalink.stop()
        await bot.db.close()


# --------------------------------------------------------------------------- #
#  The production incident, replayed
# --------------------------------------------------------------------------- #
class TestTheProductionLog:
    """The exact failure from the log: every client refused the track."""

    async def test_a_dead_track_is_tried_a_bounded_number_of_times(self, stand) -> None:
        stand.lavalink.fail("alsmi", times=100)
        await stand.play("alsmi")
        assert stand.lavalink.plays == ["alsmi"] * (MAX_PLAY_RETRIES + 1)

    async def test_attempts_are_counted_one_two_three(self, stand, caplog) -> None:
        """The log showed "attempt 1 of 3" twice: the count had been reset."""
        stand.lavalink.fail("alsmi", times=100)
        with caplog.at_level(logging.INFO, logger="bot.music"):
            await stand.play("alsmi")
        attempts = [r.args[1] for r in caplog.records if "retrying" in r.getMessage()]
        assert attempts == list(range(1, MAX_PLAY_RETRIES + 1))

    async def test_the_channel_is_told_exactly_once(self, stand) -> None:
        stand.lavalink.fail("alsmi", times=100)
        await stand.play("alsmi")
        assert len(stand.reports()) == 1

    async def test_the_report_names_the_sign_in_wall(self, stand) -> None:
        stand.lavalink.fail("alsmi", times=100)
        await stand.play("alsmi")
        assert "входа в аккаунт" in stand.reports()[0]

    async def test_one_panel_for_all_attempts(self, stand) -> None:
        """Each attempt used to repost the panel: the flicker."""
        stand.lavalink.fail("alsmi", times=100)
        await stand.play("alsmi")
        assert len(stand.panels()) == 1
        assert stand.panels()[0].deleted, "the panel outlived the dead track"

    async def test_the_real_cause_reaches_the_log(self, stand, caplog) -> None:
        """It used to say "источник не отдал поток" for every failure."""
        stand.lavalink.fail("alsmi", times=100)
        with caplog.at_level(logging.WARNING, logger="bot.music"):
            await stand.play("alsmi")
        text = caplog.text
        assert "ANDROID_VR: This video requires login." in text
        assert "WEB: No supported audio streams available" in text

    def test_wavelinks_stack_trace_wall_is_muted(self) -> None:
        """Six copies of a 60-line trace per track buried the real log."""
        from utils.logging import configure_library_loggers

        configure_library_loggers()
        assert not logging.getLogger("TrackException").isEnabledFor(logging.ERROR)
        assert logging.getLogger("bot.music").isEnabledFor(logging.WARNING)


# --------------------------------------------------------------------------- #
#  Recovery
# --------------------------------------------------------------------------- #
class TestRecovery:
    async def test_a_random_refusal_is_recovered(self, stand) -> None:
        stand.lavalink.fail("song", times=2)
        await stand.play("song")
        assert stand.lavalink.now(stand.gid) == "song"
        assert stand.reports() == []

    async def test_after_recovery_the_player_knows_what_is_playing(self, stand) -> None:
        """The buttons read player.current; it was None under a retry."""
        stand.lavalink.fail("song", times=2)
        await stand.play("song")
        assert stand.player.current is not None
        assert stand.player.current.title == "song"
        assert stand.player.playing

    async def test_after_recovery_the_pause_button_works(self, stand) -> None:
        stand.lavalink.fail("song", times=1)
        await stand.play("song")
        view = stand.live_panel_view()
        button = next(i for i in view.walk_children() if getattr(i, "label", None) == "Пауза")
        interaction = FakeInteraction(user=make_member(1, guild=stand.guild), guild=stand.guild)
        record = await drive(view, button, interaction)
        assert record.acknowledged
        assert not record.followups, f"button refused: {record.followups}"
        assert stand.player.paused

    async def test_recovery_posts_a_single_panel(self, stand) -> None:
        stand.lavalink.fail("song", times=MAX_PLAY_RETRIES)
        await stand.play("song")
        assert len(stand.panels()) == 1
        assert not stand.panels()[0].deleted

    async def test_the_last_allowed_attempt_can_still_succeed(self, stand) -> None:
        stand.lavalink.fail("song", times=MAX_PLAY_RETRIES)
        await stand.play("song")
        assert stand.lavalink.now(stand.gid) == "song"

    async def test_a_mid_stream_break_resumes_where_it_stopped(self, stand) -> None:
        await stand.play("song")
        stand.lavalink.fail_mid_stream(
            stand.gid, 95_000, "Client [MWEB] failed: Not success status code: 403"
        )
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) == "song"
        seeks = stand.lavalink.guilds[stand.gid].seeks
        assert seeks and 95_000 <= seeks[-1] < 100_000

    async def test_a_track_that_fails_at_the_start_is_not_seeked(self, stand) -> None:
        stand.lavalink.fail("song", times=1)
        await stand.play("song")
        assert stand.lavalink.guilds[stand.gid].seeks == []


# --------------------------------------------------------------------------- #
#  The queue keeps moving
# --------------------------------------------------------------------------- #
class TestTheQueueKeepsMoving:
    async def test_the_next_track_waits_for_the_retries(self, stand) -> None:
        """Retrying used to race AutoPlay, which started the next track on top."""
        stand.lavalink.fail("bad", times=2)
        await stand.play("bad", "next")
        assert stand.lavalink.plays == ["bad", "bad", "bad"]
        assert stand.lavalink.now(stand.gid) == "bad"
        assert [t.title for t in stand.player.queue] == ["next"]

    async def test_the_next_track_plays_after_giving_up(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad", "next")
        assert stand.lavalink.now(stand.gid) == "next"
        assert stand.player.current is not None and stand.player.current.title == "next"

    async def test_a_recovered_track_does_not_freeze_the_queue(self, stand) -> None:
        """Three retries are three loadFailed ends - wavelink's stop signal.

        Without the counter being reset, the track after a recovered one
        never started.
        """
        stand.lavalink.fail("flaky", times=MAX_PLAY_RETRIES)
        await stand.play("flaky", "next")
        await stand.finish()
        assert stand.lavalink.now(stand.gid) == "next"

    async def test_a_given_up_track_does_not_freeze_the_queue(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad", "next", "after")
        await stand.finish()
        assert stand.lavalink.now(stand.gid) == "after"

    async def test_a_permanent_error_is_not_retried(self, stand) -> None:
        stand.lavalink.fail("gone", times=100, message=VIDEO_UNAVAILABLE)
        await stand.play("gone", "next")
        assert stand.lavalink.plays == ["gone", "next"]
        assert len(stand.reports()) == 1

    async def test_the_report_says_the_queue_goes_on(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad", "next")
        assert "следующий" in stand.reports()[0]

    async def test_each_dead_track_is_reported_once(self, stand) -> None:
        stand.lavalink.fail("a", times=100)
        stand.lavalink.fail("b", times=100)
        await stand.play("a", "b", "ok")
        assert len(stand.reports()) == 2
        assert stand.lavalink.now(stand.gid) == "ok"


class TestARunOfDeadTracks:
    """When YouTube refuses everything, stop instead of burning the queue."""

    async def test_the_queue_pauses_after_the_limit(self, stand) -> None:
        dead = [f"dead{i}" for i in range(MAX_CONSECUTIVE_FAILURES)]
        for title in dead:
            stand.lavalink.fail(title, times=100, message=VIDEO_UNAVAILABLE)
        await stand.play(*dead, "survivor")
        assert "survivor" not in stand.lavalink.plays
        assert [t.title for t in stand.player.queue] == ["survivor"]
        assert "приостановлена" in stand.reports()[-1]

    async def test_skip_resumes_a_paused_queue(self, stand) -> None:
        """wavelink's skip does nothing when nothing is loaded."""
        dead = [f"dead{i}" for i in range(MAX_CONSECUTIVE_FAILURES)]
        for title in dead:
            stand.lavalink.fail(title, times=100, message=VIDEO_UNAVAILABLE)
        await stand.play(*dead, "survivor")
        assert await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) == "survivor"

    async def test_play_resumes_a_paused_queue(self, stand) -> None:
        dead = [f"dead{i}" for i in range(MAX_CONSECUTIVE_FAILURES)]
        for title in dead:
            stand.lavalink.fail(title, times=100, message=VIDEO_UNAVAILABLE)
        await stand.play(*dead, "survivor")
        await stand.play("requested")
        assert stand.lavalink.now(stand.gid) == "survivor"

    async def test_a_good_track_in_between_resets_the_run(self, stand) -> None:
        names = ["d1", "d2", "good", "d3", "d4", "last"]
        for title in ("d1", "d2", "d3", "d4"):
            stand.lavalink.fail(title, times=100, message=VIDEO_UNAVAILABLE)
        await stand.play(*names)
        assert stand.lavalink.now(stand.gid) == "good"
        await stand.finish()
        assert stand.lavalink.now(stand.gid) == "last"

    async def test_repeat_queue_over_dead_tracks_ends(self, stand) -> None:
        """Under "repeat queue" dead tracks used to cycle for ever."""
        stand.player.queue.mode = wavelink.QueueMode.loop_all
        for title in ("x", "y"):
            stand.lavalink.fail(title, times=10_000, message=VIDEO_UNAVAILABLE)
        await stand.play("x", "y")  # settle() raises if this never stops
        assert len(stand.lavalink.plays) <= 2 * MAX_CONSECUTIVE_FAILURES


# --------------------------------------------------------------------------- #
#  Repeat modes
# --------------------------------------------------------------------------- #
class TestRepeatModes:
    async def test_repeat_track_on_a_dead_track_stops_repeating(self, stand) -> None:
        stand.player.queue.mode = wavelink.QueueMode.loop
        stand.lavalink.fail("bad", times=10_000)
        await stand.play("bad", "next")
        assert stand.lavalink.plays.count("bad") == MAX_PLAY_RETRIES + 1
        assert stand.player.queue.mode is wavelink.QueueMode.normal
        assert stand.lavalink.now(stand.gid) == "next"

    async def test_repeat_track_survives_a_random_refusal(self, stand) -> None:
        stand.player.queue.mode = wavelink.QueueMode.loop
        stand.lavalink.fail("song", times=1)
        await stand.play("song", "next")
        assert stand.lavalink.now(stand.gid) == "song"
        assert stand.player.queue.mode is wavelink.QueueMode.loop
        assert [t.title for t in stand.player.queue] == ["next"], "retry leaked into the queue"

    async def test_repeat_queue_does_not_replay_a_dead_track(self, stand) -> None:
        stand.player.queue.mode = wavelink.QueueMode.loop_all
        stand.lavalink.fail("bad", times=10_000, message=VIDEO_UNAVAILABLE)
        await stand.play("bad", "good")
        await stand.finish()  # "good" ends, the queue wraps around
        assert stand.lavalink.plays == ["bad", "good", "good"]

    async def test_retries_do_not_pile_up_in_history(self, stand) -> None:
        stand.lavalink.fail("song", times=MAX_PLAY_RETRIES)
        await stand.play("song")
        history = [t.title for t in stand.player.queue.history]
        assert history == ["song"]


# --------------------------------------------------------------------------- #
#  User actions during and after failures
# --------------------------------------------------------------------------- #
class TestUserActions:
    async def test_asking_again_for_a_dead_track_is_answered(self, stand) -> None:
        """It used to be silent: the old budget was still spent."""
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad")
        await stand.play("bad")
        assert len(stand.reports()) == 2

    async def test_skip_during_a_scheduled_retry_really_skips(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        stand.player.queue.put(stand.lavalink.track("bad"))
        stand.player.queue.put(stand.lavalink.track("next"))
        await stand.music.maybe_start(stand.player)
        # Deliver the start and the exception, but not the end event yet.
        for _ in range(3):
            await asyncio.sleep(0)
        await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) == "next"

    async def test_skip_after_a_recovered_retry(self, stand) -> None:
        stand.lavalink.fail("song", times=1)
        await stand.play("song", "next")
        assert await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) == "next"

    async def test_skip_the_only_track(self, stand) -> None:
        await stand.play("only")
        assert await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) is None
        assert stand.player.current is None

    async def test_skip_with_nothing_at_all(self, stand) -> None:
        assert not await stand.music.skip_current(stand.player)

    async def test_skip_button_on_the_last_track_ends_the_queue(self, stand) -> None:
        await stand.play("only")
        view = stand.live_panel_view()
        button = next(i for i in view.walk_children() if getattr(i, "label", None) == "Скип")
        interaction = FakeInteraction(user=make_member(1, guild=stand.guild), guild=stand.guild)
        record = await drive(view, button, interaction)
        await stand.lavalink.settle()
        assert record.acknowledged and not record.followups
        assert stand.panels()[0].deleted
        assert stand.guild.id not in stand.music.now_messages

    async def test_stop_during_retries_is_silent_and_final(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        stand.player.queue.put(stand.lavalink.track("bad"))
        await stand.music.maybe_start(stand.player)
        await stand.music.stop_player(stand.player)
        await stand.lavalink.settle()
        assert stand.reports() == []
        assert stand.lavalink.now(stand.gid) is None
        assert stand.lavalink.plays.count("bad") <= 2


# --------------------------------------------------------------------------- #
#  Coupling to wavelink internals
# --------------------------------------------------------------------------- #
def test_wavelink_still_has_the_autoplay_error_counter() -> None:
    """The cog steers ``Player._error_count``; an upgrade must not hide a rename."""
    import inspect

    source = inspect.getsource(wavelink.Player._auto_play_event)
    assert "self._error_count >= 3" in source
    assert 'payload.reason == "loadFailed"' in source


# --------------------------------------------------------------------------- #
#  Moved from the mock-based suite, now against the real player
# --------------------------------------------------------------------------- #
class TestBookkeeping:
    async def test_a_dead_last_track_does_not_also_announce_the_queue_end(self, stand) -> None:
        """One event, one message: the failure, not "queue finished" on top."""
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad")
        texts = [_text(v) for _, v in stand._posted()]
        assert not [t for t in texts if "Очередь закончилась" in t]

    async def test_a_finished_last_track_does_announce_it(self, stand) -> None:
        await stand.play("song")
        await stand.finish()
        texts = [_text(v) for _, v in stand._posted()]
        assert [t for t in texts if "Очередь закончилась" in t]

    async def test_an_exception_without_a_player_is_logged_not_raised(self, stand, caplog) -> None:
        payload = wavelink.TrackExceptionEventPayload(
            player=None,
            track=stand.lavalink.track("orphan"),
            exception={"message": VIDEO_UNAVAILABLE, "severity": "common", "cause": ""},
        )
        with caplog.at_level(logging.WARNING, logger="bot.music"):
            await stand.music.on_wavelink_track_exception(payload)
        assert "orphan" in caplog.text

    async def test_leaving_the_guild_releases_the_failure_state(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad")
        stand.music._forget_guild(stand.gid)
        assert stand.gid not in stand.music._failures._current
        assert stand.gid not in stand.music._positions

    async def test_the_saved_session_does_not_keep_a_dead_track(self, stand) -> None:
        """A restart would otherwise replay the failure as its first act."""
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad", "next")
        saved = await stand.bot.db.load_queue(stand.gid)
        assert [t.uri for t in saved] == ["https://example/next"]
