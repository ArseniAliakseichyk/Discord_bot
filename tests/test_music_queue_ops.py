"""Seek parsing and the queue-editing commands.

These were added as part of restoring the music gaps, and the queue operations
in particular have a trap: wavelink's ``Queue.get_at`` also assigns the track to
the slot ``QueueMode.loop`` replays, so using it to reorder silently changes
what is on repeat. The tests below pin the behaviour that avoids it.
"""

from __future__ import annotations

import pytest
import wavelink

from core.bot import INITIAL_EXTENSIONS, MusicBot
from tests.interaction_harness import (
    FakeInteraction,
    make_channel,
    make_guild,
    make_member,
    make_player,
    make_track,
)
from utils.formatting import format_ms, parse_position


class TestParsePosition:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0", 0),
            ("90", 90_000),
            ("1:30", 90_000),
            ("01:30", 90_000),
            ("1:02:03", 3_723_000),
            ("  2:05  ", 125_000),
        ],
    )
    def test_accepted_forms(self, text: str, expected: int) -> None:
        assert parse_position(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "abc",
            "-5",
            "1:75",       # 75 seconds is a typo, not 1:15
            "1:2:3:4",    # too many parts
            "1:",
            ":30",
            "1.30",
            "90s",
        ],
    )
    def test_rejected_forms(self, text: str) -> None:
        assert parse_position(text) is None

    @pytest.mark.parametrize("text", ["00:45", "03:35", "1:02:03"])
    def test_round_trips_with_the_formatter(self, text: str) -> None:
        """What /now displays must parse back to the same position."""
        parsed = parse_position(text)
        assert parsed is not None
        assert format_ms(parsed) == text


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "ops.db")))
    await instance.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await instance.load_extension(extension)
    try:
        yield instance
    finally:
        await instance.db.close()


def situation(bot, *titles: str):
    guild = make_guild()
    channel = make_channel(guild=guild)
    member = make_member(1, guild=guild)
    player = make_player(guild)
    for title in titles:
        player.queue.put(make_track(title))
    music = bot.get_cog("Music")
    interaction = FakeInteraction(user=member, guild=guild, channel=channel)
    return music, player, interaction


def titles(player) -> list[str]:
    return [t.title for t in player.queue]


class TestRemove:
    async def test_removes_the_numbered_track(self, bot) -> None:
        music, player, interaction = situation(bot, "a", "b", "c")
        await music.remove.callback(music, interaction, 2)
        assert titles(player) == ["a", "c"]

    async def test_out_of_range_is_reported(self, bot) -> None:
        music, player, interaction = situation(bot, "a")
        await music.remove.callback(music, interaction, 9)
        assert titles(player) == ["a"]
        assert interaction.record.acknowledged

    async def test_empty_queue_is_reported(self, bot) -> None:
        music, player, interaction = situation(bot)
        await music.remove.callback(music, interaction, 1)
        assert interaction.record.acknowledged


class TestMove:
    async def test_moves_a_track_forward_without_touching_loop_state(self, bot) -> None:
        """get_at would set the loop slot; peek+delete must not."""
        music, player, interaction = situation(bot, "a", "b", "c")
        player.queue.mode = wavelink.QueueMode.loop

        await music.move.callback(music, interaction, 1, 3)

        assert titles(player) == ["b", "c", "a"]
        assert player.queue._loaded is None, "reordering changed what is on repeat"

    async def test_moves_a_track_backward(self, bot) -> None:
        music, player, interaction = situation(bot, "a", "b", "c")
        await music.move.callback(music, interaction, 3, 1)
        assert titles(player) == ["c", "a", "b"]

    async def test_same_position_is_a_no_op(self, bot) -> None:
        music, player, interaction = situation(bot, "a", "b")
        await music.move.callback(music, interaction, 1, 1)
        assert titles(player) == ["a", "b"]
        assert interaction.record.acknowledged

    async def test_out_of_range_leaves_the_queue_alone(self, bot) -> None:
        music, player, interaction = situation(bot, "a", "b")
        await music.move.callback(music, interaction, 1, 9)
        assert titles(player) == ["a", "b"]


class TestLoop:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [
            ("off", wavelink.QueueMode.normal),
            ("track", wavelink.QueueMode.loop),
            ("queue", wavelink.QueueMode.loop_all),
        ],
    )
    async def test_sets_the_queue_mode(self, bot, choice, expected) -> None:
        from discord import app_commands

        music, player, interaction = situation(bot, "a")
        await music.loop.callback(
            music, interaction, app_commands.Choice(name=choice, value=choice)
        )
        assert player.queue.mode is expected


class TestQueueAutocomplete:
    async def test_offers_the_queued_titles(self, bot) -> None:
        music, player, interaction = situation(bot, "alpha", "beta", "gamma")
        choices = await music._queue_autocomplete(interaction, "")
        assert [c.value for c in choices] == [1, 2, 3]
        assert choices[0].name.startswith("1. alpha")

    async def test_filters_by_what_was_typed(self, bot) -> None:
        music, player, interaction = situation(bot, "alpha", "beta", "gamma")
        choices = await music._queue_autocomplete(interaction, "gam")
        assert [c.name.split(". ", 1)[1] for c in choices] == ["gamma"]

    async def test_is_empty_without_a_player(self, bot) -> None:
        guild = make_guild()
        guild.voice_client = None
        interaction = FakeInteraction(user=make_member(1, guild=guild), guild=guild)
        assert await bot.get_cog("Music")._queue_autocomplete(interaction, "") == []

    async def test_respects_discord_limits(self, bot) -> None:
        from cogs.music import AUTOCOMPLETE_LABEL_LIMIT, AUTOCOMPLETE_LIMIT

        music, player, interaction = situation(bot, *(f"track {i}" for i in range(40)))
        choices = await music._queue_autocomplete(interaction, "")
        assert len(choices) == AUTOCOMPLETE_LIMIT
        assert all(len(c.name) <= AUTOCOMPLETE_LABEL_LIMIT for c in choices)
