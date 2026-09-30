"""The retry policy on its own, without discord or wavelink."""

from __future__ import annotations

import pytest

from tests.lavalink_stand import REAL_ALL_CLIENTS_FAILED, VIDEO_UNAVAILABLE
from utils.playback_failures import (
    RESUME_THRESHOLD_MS,
    FailureInfo,
    FailureTracker,
    Verdict,
    classify,
)

RETRYABLE = FailureInfo(retryable=True, needs_login=False, summary="x")
FATAL = FailureInfo(retryable=False, needs_login=False, summary="x")
G = 1


class TestClassify:
    def test_the_production_message(self) -> None:
        info = classify(REAL_ALL_CLIENTS_FAILED)
        assert info.retryable, "SABR and 403 reasons can differ next time"
        assert info.needs_login
        assert info.summary.startswith("TVHTML5: The page needs to be reloaded.;")
        assert "WEB_EMBEDDED_PLAYER: Video player configuration error" in info.summary

    def test_every_client_appears_once(self) -> None:
        doubled = REAL_ALL_CLIENTS_FAILED + ", caused by: " + REAL_ALL_CLIENTS_FAILED
        assert classify(doubled).summary.count("ANDROID_VR:") == 1

    def test_an_unavailable_video_is_final(self) -> None:
        info = classify(VIDEO_UNAVAILABLE)
        assert not info.retryable
        assert not info.needs_login

    def test_a_permanent_reason_wins_over_a_transient_one(self) -> None:
        message = (
            "Client [WEB] failed: No supported audio streams available\n"
            "Client [TV] failed: This video is private\n"
        )
        assert not classify(message).retryable

    def test_only_sign_in_walls_are_not_retried(self) -> None:
        message = (
            "Client [ANDROID_VR] failed: This video requires login.\n"
            "Client [TVHTML5_SIMPLY] failed: Sign in to confirm you're not a bot\n"
        )
        info = classify(message)
        assert info.needs_login
        assert not info.retryable, "asking again without signing in changes nothing"

    @pytest.mark.parametrize(
        "message",
        [
            "Something broke while playing the track.",
            "",
            None,
        ],
    )
    def test_an_unrecognised_message_gets_another_try(self, message) -> None:
        assert classify(message).retryable

    def test_a_plain_message_is_summarised_by_its_first_line(self) -> None:
        assert classify("Read timed out\n    at x.y(Z.java:1)").summary == "Read timed out"

    def test_an_empty_message_still_has_a_summary(self) -> None:
        assert classify(None).summary == "unknown error"


class TestTracker:
    def test_retries_then_gives_up(self) -> None:
        t = FailureTracker(max_retries=2)
        t.on_start(G, "a")
        verdicts = []
        for _ in range(3):
            verdicts.append(t.on_failure(G, "a", RETRYABLE).verdict)
            t.on_start(G, "a")
        assert verdicts == [Verdict.RETRY, Verdict.RETRY, Verdict.GIVE_UP]

    def test_a_retry_start_is_recognised(self) -> None:
        t = FailureTracker()
        assert t.on_start(G, "a") == (False, 0)
        t.on_failure(G, "a", RETRYABLE)
        assert t.on_start(G, "a") == (True, 0)

    def test_a_fresh_request_after_giving_up_gets_a_new_budget(self) -> None:
        t = FailureTracker(max_retries=0)
        t.on_start(G, "a")
        assert t.on_failure(G, "a", RETRYABLE).verdict is Verdict.GIVE_UP
        assert t.on_start(G, "a") == (False, 0)
        assert t.on_failure(G, "a", RETRYABLE).verdict is not Verdict.SILENT

    def test_a_duplicate_failure_after_giving_up_is_silent(self) -> None:
        t = FailureTracker(max_retries=0)
        t.on_start(G, "a")
        t.on_failure(G, "a", FATAL)
        assert t.on_failure(G, "a", FATAL).verdict is Verdict.SILENT

    def test_a_fatal_error_is_not_retried(self) -> None:
        t = FailureTracker()
        t.on_start(G, "a")
        assert t.on_failure(G, "a", FATAL).verdict is Verdict.GIVE_UP

    def test_consecutive_give_ups_halt(self) -> None:
        t = FailureTracker(max_consecutive=2)
        t.on_start(G, "a")
        assert t.on_failure(G, "a", FATAL).verdict is Verdict.GIVE_UP
        t.on_start(G, "b")
        assert t.on_failure(G, "b", FATAL).verdict is Verdict.HALT

    def test_a_played_track_ends_the_run(self) -> None:
        t = FailureTracker(max_consecutive=2)
        t.on_start(G, "a")
        t.on_failure(G, "a", FATAL)
        t.on_start(G, "ok")
        t.on_played(G)
        t.on_start(G, "b")
        assert t.on_failure(G, "b", FATAL).verdict is Verdict.GIVE_UP

    def test_resume_position_is_kept_across_early_failures(self) -> None:
        t = FailureTracker()
        t.on_start(G, "a")
        first = t.on_failure(G, "a", RETRYABLE, position_ms=60_000)
        assert first.resume_ms == 60_000
        assert t.on_start(G, "a") == (True, 60_000)
        # The retry breaks almost at once; the point to resume from stays.
        second = t.on_failure(G, "a", RETRYABLE, position_ms=1_000)
        assert second.resume_ms == 60_000

    def test_a_failure_right_at_the_start_does_not_seek(self) -> None:
        t = FailureTracker()
        t.on_start(G, "a")
        assert t.on_failure(G, "a", RETRYABLE, position_ms=RESUME_THRESHOLD_MS - 1).resume_ms == 0

    def test_cancelling_a_retry(self) -> None:
        t = FailureTracker()
        t.on_start(G, "a")
        t.on_failure(G, "a", RETRYABLE)
        assert t.cancel_pending(G) == "a"
        assert t.cancel_pending(G) is None
        assert t.on_failure(G, "a", RETRYABLE).verdict is Verdict.SILENT

    def test_silence_until_the_user_plays_again(self) -> None:
        t = FailureTracker()
        t.silence(G)
        assert t.on_start(G, "a") == (True, 0), "a late start must not redraw"
        assert t.on_failure(G, "a", FATAL).verdict is Verdict.SILENT
        t.resume_queue(G)
        assert t.on_start(G, "a") == (False, 0)

    def test_guilds_are_independent(self) -> None:
        t = FailureTracker(max_retries=0)
        t.on_start(1, "a")
        t.on_start(2, "a")
        t.on_failure(1, "a", RETRYABLE)
        assert t.on_failure(2, "a", RETRYABLE).verdict is Verdict.GIVE_UP

    def test_failure_without_a_start(self) -> None:
        """A restored session can fail before any start was observed."""
        t = FailureTracker()
        assert t.on_failure(G, "a", RETRYABLE).verdict is Verdict.RETRY

    def test_forget(self) -> None:
        t = FailureTracker()
        t.on_start(G, "a")
        t.on_failure(G, "a", RETRYABLE)
        t.silence(2)
        t.forget(G)
        t.forget(2)
        assert not t.is_pending(G)
        assert t.on_start(2, "x") == (False, 0)
