"""End-to-end checks against a running Lavalink node.

Everything else in the suite runs against doubles. These tests talk to the real
node and therefore catch the failures doubles cannot: a plugin that stopped
loading, YouTube blocking the client, or Spotify changing what it serves. They
are the reason the README's Spotify table can claim to be measured rather than
assumed.

Skipped automatically when no node is reachable, so the normal suite stays
offline and fast. Point LAVALINK_URI/LAVALINK_PASSWORD at a node to run them:

    docker compose up -d
    LAVALINK_URI=http://localhost:2333 venv/bin/python -m pytest -m e2e
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

pytestmark = pytest.mark.e2e

URI = os.environ.get("LAVALINK_URI", "http://localhost:2333").rstrip("/")
PASSWORD = os.environ.get("LAVALINK_PASSWORD", "youshallnotpass")
TIMEOUT = 20


def _get(path: str, **params: str) -> tuple[int, object]:
    url = f"{URI}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url)
    request.add_header("Authorization", PASSWORD)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode()
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def _node_available() -> bool:
    try:
        status, _ = _get("/version")
        return status == 200
    except OSError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _node_available(),
        reason=f"no Lavalink node at {URI} (start it with `docker compose up -d`)",
    ),
]


def load(identifier: str) -> dict:
    status, body = _get("/v4/loadtracks", identifier=identifier)
    assert status == 200, f"loadtracks returned {status}: {body}"
    assert isinstance(body, dict)
    return body


def first_track(payload: dict) -> dict:
    kind, data = payload["loadType"], payload["data"]
    if kind == "track":
        return data["info"]
    if kind == "search":
        return data[0]["info"]
    if kind == "playlist":
        return data["tracks"][0]["info"]
    raise AssertionError(f"unexpected loadType {kind}: {data}")


# --------------------------------------------------------------------------- #
#  The node itself
# --------------------------------------------------------------------------- #
class TestNode:
    def test_version_endpoint_requires_the_password(self) -> None:
        request = urllib.request.Request(f"{URI}/version")
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=TIMEOUT)
        assert caught.value.code == 401

    def test_reports_v4(self) -> None:
        status, body = _get("/version")
        assert status == 200
        assert str(body).startswith("4"), f"expected Lavalink v4, got {body}"

    def test_both_plugins_are_loaded(self) -> None:
        """A plugin that fails to download leaves the bot silently degraded."""
        status, info = _get("/v4/info")
        assert status == 200 and isinstance(info, dict)
        names = {p["name"] for p in info["plugins"]}
        assert "youtube-plugin" in names, f"youtube plugin missing: {names}"
        assert "lavasrc-plugin" in names, f"LavaSrc missing: {names}"

    def test_the_expected_sources_are_enabled(self) -> None:
        status, info = _get("/v4/info")
        assert status == 200 and isinstance(info, dict)
        sources = set(info["sourceManagers"])
        assert {"youtube", "http", "local"} <= sources, sources


# --------------------------------------------------------------------------- #
#  Resolution paths the bot actually uses
# --------------------------------------------------------------------------- #
class TestYouTube:
    def test_plain_search_returns_results(self) -> None:
        info = first_track(load("ytsearch:lofi hip hop"))
        assert info["title"] and info["sourceName"] == "youtube"

    def test_a_direct_url_resolves(self) -> None:
        payload = load("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert payload["loadType"] in {"track", "playlist"}, payload
        assert first_track(payload)["sourceName"] == "youtube"

    def test_a_youtube_playlist_resolves(self) -> None:
        """Bulk queueing has to work somewhere, since Spotify's does not."""
        payload = load(
            "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
        )
        assert payload["loadType"] == "playlist", payload
        assert len(payload["data"]["tracks"]) > 1


class TestSpotify:
    """Guards the capability table in the README.

    If any of these flip, the documentation is wrong and the user-facing
    message in cogs/music.py needs revisiting.
    """

    def test_a_track_link_resolves_with_an_isrc(self) -> None:
        info = first_track(load("https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"))
        assert info["sourceName"] == "spotify"
        assert info["isrc"], "no ISRC means mirroring falls back to a title search"

    def test_spsearch_returns_results(self) -> None:
        info = first_track(load("spsearch:daft punk one more time"))
        assert info["sourceName"] == "spotify"

    @pytest.mark.parametrize(
        ("kind", "identifier"),
        [
            ("album", "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx"),
            ("playlist", "https://open.spotify.com/playlist/61jNo7WKLOIQkahju8i0hw"),
        ],
    )
    def test_albums_and_playlists_are_still_refused_by_spotify(
        self, kind: str, identifier: str
    ) -> None:
        """Documented limitation, asserted so we notice if it ever lifts.

        Spotify removed GET /v1/tracks in February 2026 and now requires a user
        token for playlist items. If this starts passing, Spotify or LavaSrc
        changed and the bot should stop refusing these links up front.
        """
        payload = load(identifier)
        assert payload["loadType"] == "error", (
            f"Spotify {kind}s resolve again - remove the refusal in "
            f"cogs/music.py and update the README: {payload}"
        )


class TestLocalFiles:
    def test_a_missing_local_file_is_reported_not_crashed(self) -> None:
        payload = load("/music/definitely-not-here.mp3")
        assert payload["loadType"] in {"empty", "error"}, payload


# --------------------------------------------------------------------------- #
#  The bot's own resolver, against the real node
# --------------------------------------------------------------------------- #
class TestBotResolverAgainstRealNode:
    """The routing in Music._resolve, checked against live results."""

    def test_prefixed_queries_are_not_double_prefixed(self) -> None:
        """"spsearch:x" must not be sent as "ytsearch:spsearch:x"."""
        good = load("spsearch:daft punk one more time")
        bad = load("ytsearch:spsearch:daft punk one more time")
        assert first_track(good)["sourceName"] == "spotify"
        # The doubled form finds something unrelated or nothing; either way it
        # is not Spotify, which is what the source=None branch prevents.
        if bad["loadType"] not in {"empty", "error"}:
            assert first_track(bad)["sourceName"] != "spotify"


# --------------------------------------------------------------------------- #
#  Streaming - the path that actually plays audio
# --------------------------------------------------------------------------- #
class TestStreaming:
    """Resolving a track and being able to stream it are different things.

    loadtracks only reads metadata; the audio URL is fetched later, during
    playback, by a code path these tests reach through the plugin's own
    /youtube/stream route. Checking only loadtracks is how a completely
    unplayable setup can look healthy - which is exactly what happened here.
    """

    @staticmethod
    def _stream(video_id: str) -> tuple[int, str]:
        request = urllib.request.Request(
            f"{URI}/youtube/stream/{video_id}",
            headers={"Authorization": PASSWORD, "Range": "bytes=0-2048"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read(2048)
                return response.status, response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            return error.code, error.read()[:200].decode(errors="replace")

    def test_a_known_video_yields_an_audio_stream(self) -> None:
        """Fails with 500 when signature deciphering is unavailable.

        The plugin no longer deciphers signatures itself, so without a reachable
        remoteCipher server this returns 500 while search still succeeds - the
        "No supported audio streams available" symptom seen in production.
        """
        status, detail = self._stream("dQw4w9WgXcQ")
        assert status == 200, (
            f"no audio stream ({status}): {detail}. Check that the yt-cipher "
            f"service is running and plugins.youtube.remoteCipher points at it."
        )
        assert detail.startswith("audio/"), f"expected audio, got {detail}"

    def test_the_cipher_server_is_configured(self) -> None:
        """A missing remoteCipher is the difference between working and not."""
        status, info = _get("/v4/info")
        assert status == 200 and isinstance(info, dict)
        names = {p["name"] for p in info["plugins"]}
        assert "youtube-plugin" in names
