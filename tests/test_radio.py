"""Radio: music carries on when the queue runs out.

The complaint was "radio does not play". wavelink's own radio asked Spotify
for recommendations after a Spotify track (``sprec:``), and Spotify closed
that to bots, so it played nothing; and turning radio on in silence did
nothing until someone played a track. These run on a real wavelink player fed
by the scripted Lavalink, with YouTube's answers scripted below.
"""

from __future__ import annotations

import asyncio
from typing import Any

import discord
import pytest
from discord import app_commands

from tests.interaction_harness import FakeInteraction, drive, find_item, idle_text, make_member
from tests.lavalink_stand import VIDEO_UNAVAILABLE, Stand, view_text
from ui.controls import CID_RADIO
from utils.player import LIVE_LENGTH_MS, is_live
from utils.radio import choose, is_radio_pick, mix_url, seed_search, youtube_seed


class FakeYouTube:
    """Answers radio's lookups - searches and mixes - from a script."""

    def __init__(self, stand: Stand) -> None:
        self.stand = stand
        self.queries: list[str] = []
        self.results: dict[str, list[str]] = {}

    def mix(self, seed: str, *titles: str) -> None:
        # A real mix opens with its seed.
        self.results[mix_url(seed)] = [seed, *titles]

    def search(self, query: str, *titles: str) -> None:
        self.results[query] = list(titles)

    async def __call__(self, query: str) -> list[Any]:
        self.queries.append(query)
        await asyncio.sleep(0)  # an HTTP call
        return [self.stand.lavalink.track(t) for t in self.results.get(query, [])]


@pytest.fixture
def youtube(stand: Stand) -> FakeYouTube:
    fake = FakeYouTube(stand)
    stand.music._radio_search = fake  # type: ignore[method-assign]
    return fake


def now(stand: Stand) -> str | None:
    return stand.lavalink.now(stand.gid)


async def radio(stand: Stand, enabled: bool = True) -> str:
    told = await stand.music.set_radio(stand.player, enabled, None)
    await stand.lavalink.settle()
    return told


async def play_spotify(stand: Stand, title: str, author: str) -> None:
    stand.player.queue.put(stand.lavalink.track(title, source="spotify", author=author))
    await stand.music.maybe_start(stand.player)
    await stand.lavalink.settle()


def listener(stand: Stand) -> Any:
    member = make_member(1, guild=stand.guild)
    member.voice = discord.Object(0)
    member.voice.channel = stand.player.channel  # type: ignore[attr-defined]
    return member


async def press_radio(stand: Stand) -> None:
    view = stand.live_panel_view()
    interaction = FakeInteraction(
        user=listener(stand),
        guild=stand.guild,
        channel=stand.home,
        message=stand.music.now_messages.get(stand.gid),
    )
    record = await drive(view, find_item(view, CID_RADIO), interaction)
    assert record.acknowledged
    await stand.lavalink.settle()


# --------------------------------------------------------------------------- #
#  Carrying on
# --------------------------------------------------------------------------- #
class TestRadioCarriesOn:
    async def test_after_a_youtube_track_it_plays_that_tracks_mix(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2")
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        assert now(stand) == "like-1", "the mix opens with the seed, which just played"
        assert youtube.queries == [mix_url("song")]

    async def test_after_a_spotify_track_it_finds_the_track_on_youtube(
        self, stand, youtube
    ) -> None:
        """The production failure: radio after a Spotify link played nothing."""
        youtube.search("ytsearch:Gradusy - Меланхолия", "yt-melancholy")
        youtube.mix("yt-melancholy", "like-1")
        await play_spotify(stand, "Меланхолия", "Gradusy")
        await radio(stand)
        await stand.finish()
        assert now(stand) == "like-1"
        assert youtube.queries == ["ytsearch:Gradusy - Меланхолия", mix_url("yt-melancholy")]

    async def test_picks_follow_one_another_from_a_single_lookup(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2", "like-3")
        await stand.play("song")
        await radio(stand)
        heard = []
        for _ in range(3):
            await stand.finish()
            heard.append(now(stand))
        assert heard == ["like-1", "like-2", "like-3"]
        assert youtube.queries == [mix_url("song")]

    async def test_when_picks_run_out_it_follows_the_last_one(self, stand, youtube) -> None:
        youtube.mix("song", "like-1")
        youtube.mix("like-1", "song", "deeper")  # "song" was heard already
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        await stand.finish()
        assert now(stand) == "deeper"

    async def test_the_panel_says_radio_chose_the_track(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2")
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        text = view_text(stand.live_panel_view())
        assert "📻 подобрало радио" in text
        assert "📻 радио" in text
        assert "like-2" in text, "Далее lists the coming pick"

    async def test_nothing_found_says_so_instead_of_going_quiet(self, stand, youtube) -> None:
        await stand.play("song")
        await radio(stand)
        panel = stand.music.now_messages[stand.gid]
        await stand.finish()
        assert now(stand) is None
        assert "Радио не нашло похожих треков" in (idle_text(panel) or "")


# --------------------------------------------------------------------------- #
#  Turning it on and off
# --------------------------------------------------------------------------- #
class TestSwitching:
    async def test_on_in_silence_starts_from_the_last_track_played(self, stand, youtube) -> None:
        """It used to do nothing until someone played a track."""
        youtube.mix("song", "like-1")
        await stand.play("song")
        await stand.finish()
        assert now(stand) is None
        told = await radio(stand)
        assert now(stand) == "like-1"
        assert "song" in told

    async def test_on_with_nothing_ever_played_says_what_to_do(self, stand, youtube) -> None:
        told = await radio(stand)
        assert "/play" in told
        assert youtube.queries == []
        assert now(stand) is None

    async def test_off_drops_the_picks_and_lets_the_queue_end(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2")
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        await radio(stand, False)
        assert stand.player.auto_queue.is_empty
        await stand.finish()
        assert now(stand) is None

    async def test_the_command_answers_privately(self, stand, youtube) -> None:
        youtube.mix("song", "like-1")
        await stand.play("song")
        interaction = FakeInteraction(user=listener(stand), guild=stand.guild, channel=stand.home)
        choice = app_commands.Choice(name="Включить (радио)", value="on")
        await stand.music.autoplay.callback(stand.music, interaction, choice)
        await stand.lavalink.settle()
        reply = interaction.record.followups[0]
        assert reply.get("ephemeral") is True
        assert "Радио включено" in reply["content"]
        assert stand.music.radio_on(stand.gid)

    async def test_the_panel_button_switches_it(self, stand, youtube) -> None:
        await stand.play("song")
        await press_radio(stand)
        assert stand.music.radio_on(stand.gid)
        button = find_item(stand.live_panel_view(), CID_RADIO)
        assert button.style is discord.ButtonStyle.success
        await press_radio(stand)
        assert not stand.music.radio_on(stand.gid)


# --------------------------------------------------------------------------- #
#  Radio gives way
# --------------------------------------------------------------------------- #
class TestRadioGivesWay:
    async def test_a_queued_track_plays_before_the_next_pick(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2")
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        stand.player.queue.put(stand.lavalink.track("mine"))
        await stand.finish()
        assert now(stand) == "mine"

    async def test_after_someones_track_radio_follows_that_track(self, stand, youtube) -> None:
        youtube.mix("song", "like-1", "like-2")
        youtube.mix("mine", "like-mine")
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        stand.player.queue.put(stand.lavalink.track("mine"))
        await stand.finish()
        await stand.finish()
        assert now(stand) == "like-mine", "not like-2, picked for an older track"

    async def test_stop_turns_radio_off(self, stand, youtube) -> None:
        youtube.mix("song", "like-1")
        await stand.play("song")
        await radio(stand)
        await stand.music.stop_player(stand.player)
        await stand.lavalink.settle()
        assert not stand.music.radio_on(stand.gid)
        assert now(stand) is None
        assert youtube.queries == []

    async def test_repeat_track_is_left_alone(self, stand, youtube) -> None:
        import wavelink

        youtube.mix("song", "like-1")
        await stand.play("song")
        await radio(stand)
        stand.player.queue.mode = wavelink.QueueMode.loop
        await stand.finish()
        assert now(stand) == "song"
        assert youtube.queries == []

    async def test_skip_on_the_last_track_moves_to_a_pick(self, stand, youtube) -> None:
        youtube.mix("song", "like-1")
        await stand.play("song")
        await radio(stand)
        assert await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert now(stand) == "like-1"


# --------------------------------------------------------------------------- #
#  Picks that cannot play
# --------------------------------------------------------------------------- #
class TestFailingPicks:
    async def test_a_dead_pick_hands_over_to_the_next(self, stand, youtube) -> None:
        youtube.mix("song", "dead", "like-2")
        stand.lavalink.fail("dead", 1, VIDEO_UNAVAILABLE)
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        assert now(stand) == "like-2"
        assert any("Играю следующий трек" in r for r in stand.reports())

    async def test_picks_failing_in_a_row_stop_radio_rather_than_loop(self, stand, youtube) -> None:
        youtube.mix("song", "d1", "d2", "d3", "d4", "d5")
        for title in ("d1", "d2", "d3", "d4", "d5"):
            stand.lavalink.fail(title, 1, VIDEO_UNAVAILABLE)
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        assert stand.lavalink.plays == ["song", "d1", "d2", "d3"]
        assert now(stand) is None or now(stand) == "d3"
        assert any("приостановлена" in (idle_text(m) or "") for m in stand.panels())

    async def test_skip_after_the_halt_starts_radio_again(self, stand, youtube) -> None:
        youtube.mix("song", "d1", "d2", "d3", "like-4")
        for title in ("d1", "d2", "d3"):
            stand.lavalink.fail(title, 1, VIDEO_UNAVAILABLE)
        await stand.play("song")
        await radio(stand)
        await stand.finish()
        assert await stand.music.skip_current(stand.player)
        await stand.lavalink.settle()
        assert now(stand) == "like-4"


# --------------------------------------------------------------------------- #
#  The choices, without a player
# --------------------------------------------------------------------------- #
def _track(title: str, **info: Any) -> Any:
    import wavelink

    from tests.lavalink_stand import track_data

    return wavelink.Playable(track_data(title, **info))


class TestChoices:
    def test_mix_url_is_youtubes_radio_playlist(self) -> None:
        assert mix_url("abc") == "https://www.youtube.com/watch?v=abc&list=RDabc"

    def test_only_youtube_tracks_seed_a_mix_directly(self) -> None:
        assert youtube_seed(_track("v1")) == "v1"
        assert youtube_seed(_track("s1", source="spotify")) is None

    def test_search_names_the_artist_once(self) -> None:
        assert seed_search(_track("Song", author="Band")) == "ytsearch:Band - Song"
        assert seed_search(_track("Band - Song", author="Band")) == "ytsearch:Band - Song"

    def test_choose_skips_played_live_and_too_long(self) -> None:
        mix = [
            _track("seed"),
            _track("played"),
            _track("live", stream=True),
            _track("lofi", length=LIVE_LENGTH_MS * 1000),
            _track("long", length=10_000_000),
            _track("ok"),
            _track("ok"),
        ]
        picks = choose(mix, played={"seed", "played"}, too_long=lambda t: t.title == "long")
        assert [t.title for t in picks] == ["ok"]

    def test_choose_stops_at_the_limit(self) -> None:
        picks = choose([_track(f"t{i}") for i in range(30)], played=(), too_long=lambda t: False)
        assert len(picks) == 10

    def test_a_pick_is_recognisable(self) -> None:
        from utils.radio import mark_radio_pick

        track = _track("x")
        assert not is_radio_pick(track)
        mark_radio_pick(track)
        assert is_radio_pick(track)


class TestLive:
    def test_youtube_broadcast_disguised_as_a_years_long_track_is_live(self) -> None:
        """lofi hip hop radio came back with isStream false and 121 601 512 s."""
        assert is_live(_track("lofi", length=121_601_512_000))

    def test_a_three_hour_mix_is_not_live(self) -> None:
        assert not is_live(_track("mix", length=10_801_000))

    def test_a_flagged_stream_is_live(self) -> None:
        assert is_live(_track("radio", stream=True, length=0))
