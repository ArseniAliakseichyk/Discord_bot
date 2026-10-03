"""Links that loaded as nothing in production on 2026-10-03.

* ``watch?v=X&list=PL...`` with a private or deleted playlist: the YouTube
  source failed the whole link ("The playlist does not exist") although the
  video plays - four attempts in a row, each "could not find the track".
* A Spotify artist page: LavaSrc's call answered 403.
* A Spotify *search page* link: not a track at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import wavelink

from cogs.music import (
    MSG_PLAYLIST_UNAVAILABLE,
    MSG_SPOTIFY_ARTIST,
    Music,
    SpotifyLinkUnsupported,
)
from tests.interaction_harness import FakeInteraction, make_member
from tests.lavalink_stand import Stand, track_data
from utils.links import spotify_search_text, youtube_video_only

PLAYLIST_LINK = (
    "https://www.youtube.com/watch?v=XpqH6Ir-MYM&list=PLB2-YC0bPI3ub07ml901BmSJ87bYJMuTL"
)


def load_error() -> wavelink.LavalinkLoadException:
    return wavelink.LavalinkLoadException(
        data={
            "message": "Something went wrong while looking up the track.",
            "severity": "fault",
            "cause": "AllClientsFailedException: The playlist does not exist.",
        }
    )


class FakeSearch:
    """``wavelink.Playable.search`` as the production node answered it."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, Any]] = []

    async def __call__(self, query: str, *, source: Any = None, node: Any = None) -> Any:
        self.queries.append((query, source))
        if "list=PL" in query:
            raise load_error()
        return [wavelink.Playable(track_data(query))]


@pytest.fixture
def search(monkeypatch: pytest.MonkeyPatch) -> FakeSearch:
    fake = FakeSearch()
    monkeypatch.setattr(wavelink.Playable, "search", fake)
    return fake


@pytest.fixture
def cog(tmp_path: Path) -> Music:
    settings = SimpleNamespace(
        music_folder=str(tmp_path),
        lavalink_local_dir="/music",
        spotify_enabled=True,
        max_track_length=0,
    )
    return Music(SimpleNamespace(settings=settings))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
#  Pure link reading
# --------------------------------------------------------------------------- #
class TestYoutubeVideoOnly:
    @pytest.mark.parametrize(
        ("link", "video"),
        [
            (PLAYLIST_LINK, "https://www.youtube.com/watch?v=XpqH6Ir-MYM"),
            (
                "https://www.youtube.com/watch?v=aaWQwEQ1mdQ&list=PLB2&index=2",
                "https://www.youtube.com/watch?v=aaWQwEQ1mdQ",
            ),
            ("https://youtu.be/abc123?list=PLx", "https://www.youtube.com/watch?v=abc123"),
            (
                "https://music.youtube.com/watch?v=abc&list=RDabc",
                "https://www.youtube.com/watch?v=abc",
            ),
        ],
    )
    def test_takes_the_video_out_of_a_playlist_link(self, link: str, video: str) -> None:
        assert youtube_video_only(link) == video

    @pytest.mark.parametrize(
        "link",
        [
            "https://www.youtube.com/watch?v=abc",  # no playlist: nothing to fall back from
            "https://www.youtube.com/playlist?list=PLx",  # a playlist with no video
            "https://example.com/watch?v=abc&list=PLx",
            "просто запрос",
        ],
    )
    def test_leaves_other_links_alone(self, link: str) -> None:
        assert youtube_video_only(link) is None


class TestSpotifySearchText:
    def test_reads_the_words_from_the_production_link(self) -> None:
        link = (
            "https://open.spotify.com/search/%D0%9F%D0%BE%D0%B3%D1%80%D1%83%D1%81%D1%82%D0%B8"
            "%D1%82%D1%8C?flow_ctx=25d080f2-2b5b-44fe-8fd0-8cabe118d8fc%3A1791079636"
        )
        assert spotify_search_text(link) == "Погрустить"

    def test_a_locale_prefix_is_skipped(self) -> None:
        assert spotify_search_text("https://open.spotify.com/intl-pl/search/daft%20punk") == (
            "daft punk"
        )

    @pytest.mark.parametrize(
        "link",
        [
            "https://open.spotify.com/track/65s1j8i5TSBsWEFjhlgewX",
            "https://open.spotify.com/search/",
            "https://example.com/search/words",
        ],
    )
    def test_other_links_are_not_searches(self, link: str) -> None:
        assert spotify_search_text(link) is None


# --------------------------------------------------------------------------- #
#  Resolution
# --------------------------------------------------------------------------- #
class TestLookup:
    async def test_a_dead_playlist_falls_back_to_its_video(self, cog, search) -> None:
        result, note = await cog._lookup(PLAYLIST_LINK)
        assert note == MSG_PLAYLIST_UNAVAILABLE
        assert [q for q, _ in search.queries] == [
            PLAYLIST_LINK,
            "https://www.youtube.com/watch?v=XpqH6Ir-MYM",
        ]
        assert result

    async def test_a_link_without_a_playlist_still_fails_plainly(self, cog, monkeypatch) -> None:
        async def broken(query: str, **_: Any) -> Any:
            raise load_error()

        monkeypatch.setattr(wavelink.Playable, "search", broken)
        with pytest.raises(wavelink.LavalinkLoadException):
            await cog._lookup("https://www.youtube.com/watch?v=gone")

    async def test_a_spotify_search_page_becomes_a_youtube_search(self, cog, search) -> None:
        await cog._lookup("https://open.spotify.com/search/%D0%9F%D0%BE%D0%B3%D1%80%D1%83")
        assert search.queries == [("Погру", wavelink.TrackSource.YouTube)]

    async def test_a_spotify_artist_is_refused_with_the_reason(self, cog, search) -> None:
        with pytest.raises(SpotifyLinkUnsupported) as refusal:
            await cog._lookup("https://open.spotify.com/artist/5zbAdSKQiTetVoHnbHvsDg?si=x")
        assert str(refusal.value) == MSG_SPOTIFY_ARTIST
        assert search.queries == [], "Lavalink is not asked for what Spotify refuses"

    def test_a_spotify_track_is_not_an_artist(self) -> None:
        assert not Music._is_spotify_artist("https://open.spotify.com/track/65s1j8i5TSBsWEFjhlgewX")


class TestPlayCommand:
    async def test_play_queues_the_video_and_says_the_playlist_was_unavailable(
        self, stand: Stand, search
    ) -> None:
        member = make_member(1, guild=stand.guild)
        member.voice = SimpleNamespace(channel=stand.player.channel)
        stand.lavalink.register(wavelink.Playable(track_data(PLAYLIST_LINK.split("&")[0])))
        interaction = FakeInteraction(user=member, guild=stand.guild, channel=stand.home)
        await stand.music.play.callback(stand.music, interaction, PLAYLIST_LINK)
        await stand.lavalink.settle()
        reply = interaction.record.followups[0]["content"]
        assert "Добавлен трек" in reply
        assert MSG_PLAYLIST_UNAVAILABLE in reply
        assert stand.lavalink.now(stand.gid) == "https://www.youtube.com/watch?v=XpqH6Ir-MYM"


# --------------------------------------------------------------------------- #
#  Length
# --------------------------------------------------------------------------- #
class TestLength:
    def test_there_is_no_length_limit_by_default(self, make_settings) -> None:
        """53-minute and 3-hour mixes were refused by the old 20-minute default."""
        assert make_settings().max_track_length == 0

    def test_a_disguised_broadcast_passes_a_set_limit(self, cog) -> None:
        cog.bot.settings.max_track_length = 1200
        lofi = wavelink.Playable(track_data("lofi", length=121_601_512_000))
        mix = wavelink.Playable(track_data("mix", length=10_801_000))
        assert not cog._track_too_long(lofi)
        assert cog._track_too_long(mix)
