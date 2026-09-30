"""The startup whitelist audit, whose only action - leaving - cannot be undone.

A lost ``data/bot.db`` once made the bot leave the server it served: the
whitelist lived in that file, so on the next start every guild looked
unauthorized. Only a server admin can invite a bot back.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from core.bot import MusicBot
from tests.interaction_harness import make_channel, make_guild


@pytest.fixture
async def events(tmp_path, make_settings):
    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "audit.db")))
    await bot.db.connect()
    await bot.load_extension("cogs.events")
    try:
        yield bot, bot.get_cog("Events")
    finally:
        await bot.db.close()


def joined(guild_id: int):
    guild = make_guild(guild_id)
    guild.leave = AsyncMock()
    guild.system_channel = make_channel(1, guild=guild)
    guild.text_channels = []
    return guild


async def audit(bot, cog, guilds) -> None:
    with patch.object(type(bot), "guilds", new_callable=PropertyMock, return_value=guilds):
        await cog._audit_guilds()


async def test_an_empty_whitelist_never_empties_the_bot(events, caplog) -> None:
    bot, cog = events
    guild = joined(411981432768954369)
    with caplog.at_level(logging.ERROR, logger="bot.events"):
        await audit(bot, cog, [guild])
    guild.leave.assert_not_awaited()
    guild.system_channel.send.assert_not_awaited()
    assert "whitelist is empty" in caplog.text
    assert "411981432768954369" in caplog.text


async def test_a_stranger_is_still_left_when_the_whitelist_exists(events) -> None:
    bot, cog = events
    await bot.db.authorize_guild(1, added_by=None)
    mine, stranger = joined(1), joined(2)
    await audit(bot, cog, [mine, stranger])
    mine.leave.assert_not_awaited()
    stranger.leave.assert_awaited_once()


async def test_no_guilds_and_no_whitelist_is_a_fresh_install(events, caplog) -> None:
    bot, cog = events
    with caplog.at_level(logging.ERROR, logger="bot.events"):
        await audit(bot, cog, [])
    assert "whitelist is empty" not in caplog.text


async def test_joining_with_an_empty_whitelist_still_leaves(events) -> None:
    """A fresh bot invited by a stranger must not stay just because nothing is set up."""
    bot, cog = events
    guild = joined(3)
    await cog.on_guild_join(guild)
    guild.leave.assert_awaited_once()


