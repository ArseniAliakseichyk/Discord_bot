"""Radio: when the queue runs out, carry on with tracks like the last one.

This replaces wavelink's ``AutoPlayMode.enabled``. For a Spotify track that
mode asks Spotify for recommendations (``sprec:``), and Spotify closed that
endpoint to bots: Lavalink answers it with an empty result, so radio after a
Spotify link played nothing at all. YouTube's own mix - the "RD" playlist
YouTube builds for every video - still answers, and checked against a live
node on 2026-10-03 it returns 25 tracks. A YouTube track seeds it directly;
anything else is first found on YouTube by artist and title.

Only the choices live here. The cog owns the state and the Lavalink calls.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable

import wavelink

from utils.player import is_live

#: Tracks taken from one mix. The rest of a 25-track mix is mostly the same
#: artists again; a fresh mix from a later seed drifts more naturally.
RADIO_BATCH = 10

#: How many played identifiers are remembered, so radio does not repeat itself.
RADIO_MEMORY = 200

#: Shown as who queued a radio pick.
RADIO_REQUESTER = "📻 Радио"

_YOUTUBE_SOURCES = frozenset({"youtube", "youtubemusic"})


def mix_url(video_id: str) -> str:
    """YouTube's mix for ``video_id``: the video, then ones like it."""
    return f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"


def youtube_seed(track: wavelink.Playable) -> str | None:
    """The video id to build a mix from, if ``track`` is a YouTube video."""
    if (track.source or "").lower() in _YOUTUBE_SOURCES and track.identifier:
        return track.identifier
    return None


def seed_search(track: wavelink.Playable) -> str | None:
    """A YouTube search that finds ``track`` (for seeds from other sources)."""
    title = (track.title or "").strip()
    if not title:
        return None
    author = (track.author or "").strip()
    if author and author.lower() not in title.lower():
        return f"ytsearch:{author} - {title}"
    return f"ytsearch:{title}"


def is_radio_pick(track: wavelink.Playable) -> bool:
    """Whether radio chose ``track`` (rather than a person)."""
    extras = getattr(track, "extras", None)
    return bool(getattr(extras, "radio", False))


def mark_radio_pick(track: wavelink.Playable) -> None:
    track.extras = {"requester": RADIO_REQUESTER, "radio": True}


def choose(
    candidates: Iterable[wavelink.Playable],
    *,
    played: Collection[str],
    too_long: Callable[[wavelink.Playable], bool],
    limit: int = RADIO_BATCH,
) -> list[wavelink.Playable]:
    """The picks worth queueing from a mix, in the mix's order.

    A mix opens with its seed and keeps no memory of what was heard, so
    anything already played goes. Live broadcasts go too: one would end the
    radio, since it never finishes.
    """
    picks: list[wavelink.Playable] = []
    seen = set(played)
    for track in candidates:
        key = track.identifier or track.uri or track.title
        if key in seen or is_live(track) or too_long(track):
            continue
        seen.add(key)
        picks.append(track)
        if len(picks) >= limit:
            break
    return picks
