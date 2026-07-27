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
