"""Rules every slash command must follow, checked over the live command tree."""

from __future__ import annotations

import discord
import pytest
from discord import app_commands

from core.bot import INITIAL_EXTENSIONS, MusicBot
from tests.interaction_harness import FakeInteraction, make_channel, make_guild, make_member


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "policy.db")))
    await instance.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await instance.load_extension(extension)
    try:
        yield instance
    finally:
        await instance.db.close()


def _checks(command: app_commands.Command) -> list[str]:
    return [getattr(check, "__qualname__", "") for check in command.checks]


async def test_every_command_checks_the_server_is_authorized(bot) -> None:
    """A private bot must refuse everywhere it is not whitelisted.

    Owner commands are the exception: they are how a server gets whitelisted.
    """
    missing = [
        command.qualified_name
        for command in bot.tree.walk_commands()
        if not isinstance(command, app_commands.Group)
        and not any("guild_authorized" in c or "is_owner" in c for c in _checks(command))
    ]
    assert not missing, f"commands without guild_authorized(): {missing}"


async def test_announce_refuses_a_link_that_is_not_http(bot) -> None:
    guild = make_guild()
    channel = make_channel(10, guild=guild)
    channel.__class__ = discord.TextChannel  # isinstance() in the command
    member = make_member(1, guild=guild)
    interaction = FakeInteraction(user=member, guild=guild, channel=channel)
    admin = bot.get_cog("Admin")
    await admin.announce.callback(admin, interaction, channel, None, "file:///etc/passwd", None)
    assert interaction.record.messages
    assert "https://" in interaction.record.messages[0]["content"]
    assert not interaction.record.modals, "the form must not open with a bad link"
