"""Reading the links people paste into /play.

Pure functions, no network: they decide what to ask Lavalink for when the
link as pasted cannot be loaded.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_SPOTIFY_HOSTS = frozenset({"open.spotify.com", "play.spotify.com"})


def youtube_video_only(url: str) -> str | None:
    """The video alone from a link that also names a playlist.

    ``watch?v=X&list=PL...`` loads as the whole playlist, and when that
    playlist is private or deleted the YouTube source fails the link outright
    ("The playlist does not exist") although the video itself plays. ``None``
    when the link is not a video-in-a-playlist link.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = parts.netloc.lower()
    query = parse_qs(parts.query)
    if "list" not in query:
        return None
    if host in _YOUTUBE_HOSTS and parts.path == "/watch":
        video = (query.get("v") or [""])[0]
    elif host in _SHORT_HOSTS:
        video = parts.path.strip("/")
    else:
        return None
    if not video:
        return None
    return f"https://www.youtube.com/watch?v={video}"


def spotify_search_text(url: str) -> str | None:
    """The words from a Spotify search page link (``open.spotify.com/search/...``).

    It is the address bar of Spotify's search, not a track, so nothing can
    load it; the words in it make an ordinary search instead.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.netloc.lower() not in _SPOTIFY_HOSTS:
        return None
    segments = [s for s in parts.path.split("/") if s]
    # /search/<words>, optionally after a locale segment such as /intl-pl/.
    if segments and segments[0].startswith("intl-"):
        segments = segments[1:]
    if len(segments) < 2 or segments[0] != "search":
        return None
    words = unquote(segments[1]).strip()
    return words or None
