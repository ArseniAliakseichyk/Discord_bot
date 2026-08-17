"""Local-file resolution must stay inside the configured music folder."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cogs.music import Music


@pytest.fixture
def music_cog(tmp_path: Path) -> Music:
    library = tmp_path / "music"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"id3")
    (library / "sub").mkdir()
    (library / "sub" / "deep.mp3").write_bytes(b"id3")
    # Something juicy just outside the library.
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    bot = SimpleNamespace(
        settings=SimpleNamespace(music_folder=str(library), lavalink_local_dir="/music")
    )
    return Music(bot)  # type: ignore[arg-type]


class TestLocalFile:
    def test_resolves_a_file_in_the_library(self, music_cog: Music) -> None:
        assert music_cog._local_file("song.mp3") == "/music/song.mp3"

    def test_resolves_a_file_in_a_subdirectory(self, music_cog: Music) -> None:
        assert music_cog._local_file("sub/deep.mp3") == "/music/sub/deep.mp3"

    @pytest.mark.parametrize(
        "query",
        [
            "../secret.txt",
            "../../etc/passwd",
            "sub/../../secret.txt",
            "/etc/passwd",
        ],
    )
    def test_traversal_is_refused(self, music_cog: Music, query: str) -> None:
        # Falls through to the YouTube search path instead of reading the file.
        assert music_cog._local_file(query) is None

    def test_missing_file_falls_through(self, music_cog: Music) -> None:
        assert music_cog._local_file("nope.mp3") is None

    def test_a_search_phrase_is_not_mistaken_for_a_path(self, music_cog: Music) -> None:
        assert music_cog._local_file("rick astley never gonna give you up") is None

    def test_container_path_uses_the_resolved_relative_name(
        self, music_cog: Music
    ) -> None:
        # The raw query is never interpolated: "sub/./deep.mp3" normalises first.
        assert music_cog._local_file("sub/./deep.mp3") == "/music/sub/deep.mp3"


class TestSpotifyRouting:
    """Spotify link handling.

    Albums and playlists are refused up front: verified against the live Web
    API, Spotify answers ``/v1/tracks?ids=`` with 403 and
    ``/v1/playlists/{id}/items`` with 401 for client-credentials apps, so
    LavaSrc cannot list their contents and the user deserves a real reason.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx",
            "https://open.spotify.com/playlist/61jNo7WKLOIQkahju8i0hw",
            "HTTPS://OPEN.SPOTIFY.COM/ALBUM/X",
            "https://open.spotify.com/intl-pl/album/abc",
        ],
    )
    def test_albums_and_playlists_are_detected(self, query: str) -> None:
        from cogs.music import Music

        assert Music._is_spotify_bulk(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv",
            "spsearch:daft punk",
            "https://www.youtube.com/playlist?list=PL123",
            "просто запрос",
        ],
    )
    def test_supported_queries_are_not_refused(self, query: str) -> None:
        from cogs.music import Music

        assert Music._is_spotify_bulk(query) is False

    def test_youtube_playlists_stay_allowed(self) -> None:
        """The refusal must be Spotify-specific, not "playlist" as a word."""
        from cogs.music import Music

        assert Music._is_spotify("https://www.youtube.com/playlist?list=X") is False
