"""What to do when a track will not play.

Kept free of discord and wavelink objects so the policy can be tested on its
own. The cog feeds it events and carries out the verdict; this module only
decides.

Two facts about YouTube shape the policy:

* Some refusals are random. The same request for the same video alternates
  between a SABR-only answer (no stream URL) and a playable one, so a couple
  of further attempts turn a share of failures into playback.
* Others are not. "Video unavailable" or "This video is private" will say the
  same thing however often it is asked, and retrying them only delays the
  next track and fills the log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

#: Extra attempts a track gets after its first failure.
MAX_PLAY_RETRIES = 3

#: Tracks in a row that may fail outright before the queue is paused. Without
#: a limit, a queue of dead tracks - or one dead track under "repeat queue" -
#: would cycle through failures for as long as anyone is listening.
MAX_CONSECUTIVE_FAILURES = 3

#: A failure further into a track than this resumes where it broke off rather
#: than from the start.
RESUME_THRESHOLD_MS = 3_000

_CLIENT_LINE = re.compile(r"Client \[(?P<client>[^\]]+)\] failed: (?P<reason>[^\n]+)")

# Answers that can differ on the next request.
_TRANSIENT = (
    "no supported audio streams",  # SABR-only response, varies per request
    "status code: 403",  # stream URL refused, a fresh one often works
    "player api response: 400",
    "needs to be reloaded",
    "timed out",
    "connection reset",
    "remote host terminated",
    "premature eof",
    "something went wrong",
)

# Answers about the video itself; asking again changes nothing.
_PERMANENT = (
    "video unavailable",
    "this video is unavailable",
    "this video is private",
    "has been removed",
    "copyright",
    "not available in your country",
    "not made this video available",
)

_LOGIN = (
    "requires login",
    "sign in to confirm",
    "login required",
    "confirm your age",
)


@dataclass(frozen=True)
class FailureInfo:
    """A Lavalink track exception, reduced to what the policy needs."""

    retryable: bool
    needs_login: bool
    #: One line: every client and its reason, or the first line of the message.
    summary: str


def classify(message: str | None) -> FailureInfo:
    """Read a Lavalink exception message.

    The youtube plugin reports "All clients failed" followed by one
    ``Client [NAME] failed: reason`` line per client it tried; the reasons are
    what decide whether another attempt can help.
    """
    text = (message or "").strip()
    reasons: dict[str, str] = {}
    for match in _CLIENT_LINE.finditer(text):
        # dict keeps the first reason per client and drops the duplicate list
        # some Lavalink builds append as the "cause".
        reasons.setdefault(match["client"], match["reason"].strip())

    if reasons:
        summary = "; ".join(f"{name}: {why}" for name, why in reasons.items())
        lowered = [why.lower() for why in reasons.values()]
    else:
        summary = text.splitlines()[0] if text else "unknown error"
        lowered = [text.lower()]

    # A video is gone only if *every* client says so. One client's
    # "unavailable" is often about that client alone - the embedded player
    # reports it for any video whose owner disabled embedding - and treating
    # it as final once stopped every retry of a playable track.
    permanent = all(any(p in why for p in _PERMANENT) for why in lowered)
    transient = any(t in why for why in lowered for t in _TRANSIENT)
    # With no recognisable reason at all, one more attempt costs little.
    retryable = not permanent and (transient or not reasons)
    needs_login = any(p in why for why in lowered for p in _LOGIN)
    return FailureInfo(retryable=retryable, needs_login=needs_login, summary=summary)


class Verdict(Enum):
    RETRY = "retry"  # play the same track again
    GIVE_UP = "give-up"  # tell the channel once, move on to the next track
    HALT = "halt"  # tell the channel, and stop advancing the queue
    SILENT = "silent"  # already reported; say nothing more


@dataclass
class _Attempt:
    key: str
    attempts: int = 0
    #: A retry has been scheduled and its track_start has not arrived yet.
    pending: bool = False
    resume_ms: int = 0
    done: bool = False


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    attempt: int
    resume_ms: int = 0


class FailureTracker:
    """Per-guild attempt bookkeeping.

    The event order Lavalink produces for a failing track is
    ``TrackStart -> TrackException -> TrackEnd(loadFailed)``, and a scheduled
    retry produces the same three again. Telling a retry's start apart from a
    genuinely new request for the same track is the whole difficulty: counting
    the retry as new resets the budget and loops forever, while counting a
    user's deliberate re-request as a retry leaves it silently ignored. The
    ``pending`` flag is what distinguishes them - only the tracker sets it, and
    only for a retry it scheduled.
    """

    def __init__(
        self,
        *,
        max_retries: int = MAX_PLAY_RETRIES,
        max_consecutive: int = MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self.max_retries = max_retries
        self.max_consecutive = max_consecutive
        self._current: dict[int, _Attempt] = {}
        self._consecutive: dict[int, int] = {}
        # Guilds where playback was stopped on purpose. Lavalink may still
        # deliver events for the track that was loading at that moment; they
        # describe something the user has already dismissed.
        self._silenced: set[int] = set()

    def on_start(self, guild_id: int, key: str) -> tuple[bool, int]:
        """A track started. Returns ``(is_retry, resume_ms)``."""
        if guild_id in self._silenced:
            return True, 0  # a late event for a stopped track: not news
        state = self._current.get(guild_id)
        if state is not None and state.pending and state.key == key:
            state.pending = False
            # resume_ms is kept: if this attempt breaks before reaching it,
            # the next one must still aim for the furthest point heard.
            return True, state.resume_ms
        # A new track, or the same one asked for again: a fresh budget.
        self._current[guild_id] = _Attempt(key=key)
        return False, 0

    def on_failure(
        self, guild_id: int, key: str, info: FailureInfo, position_ms: int = 0
    ) -> Decision:
        if guild_id in self._silenced:
            return Decision(Verdict.SILENT, 0)
        state = self._current.get(guild_id)
        if state is None or state.key != key:
            # No start was seen (a restore, or events racing a reconnect).
            state = _Attempt(key=key)
            self._current[guild_id] = state
        if state.done:
            return Decision(Verdict.SILENT, state.attempts)

        state.attempts += 1
        state.pending = False
        if info.retryable and state.attempts <= self.max_retries:
            state.pending = True
            # Resume a stream that broke mid-way, keeping the furthest point
            # reached so a retry that fails early does not rewind it.
            if position_ms >= RESUME_THRESHOLD_MS:
                state.resume_ms = max(state.resume_ms, position_ms)
            return Decision(Verdict.RETRY, state.attempts, state.resume_ms)

        state.done = True
        failed = self._consecutive.get(guild_id, 0) + 1
        self._consecutive[guild_id] = failed
        verdict = Verdict.HALT if failed >= self.max_consecutive else Verdict.GIVE_UP
        return Decision(verdict, state.attempts)

    def on_played(self, guild_id: int) -> None:
        """A track ended some way other than failing to load."""
        self._consecutive.pop(guild_id, None)
        state = self._current.get(guild_id)
        if state is not None and not state.pending:
            self._current.pop(guild_id, None)

    def cancel_pending(self, guild_id: int) -> str | None:
        """Withdraw a scheduled retry (the user skipped). Returns its key."""
        state = self._current.get(guild_id)
        if state is None or not state.pending:
            return None
        state.pending = False
        state.done = True
        return state.key

    def resume_queue(self, guild_id: int) -> None:
        """The user asked for playback: a new start, whatever came before."""
        self._consecutive.pop(guild_id, None)
        self._silenced.discard(guild_id)

    def silence(self, guild_id: int) -> None:
        """Playback was stopped; ignore stragglers until the user plays again."""
        self._current.pop(guild_id, None)
        self._consecutive.pop(guild_id, None)
        self._silenced.add(guild_id)

    def is_pending(self, guild_id: int) -> bool:
        state = self._current.get(guild_id)
        return state is not None and state.pending

    def forget(self, guild_id: int) -> None:
        self._current.pop(guild_id, None)
        self._consecutive.pop(guild_id, None)
        self._silenced.discard(guild_id)
