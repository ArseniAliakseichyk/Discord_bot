"""Only listeners in the bot's voice channel may steer playback."""

from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest

from tests.interaction_harness import make_guild, make_member
from utils.checks import bot_voice_refusal

#: Every command that changes what is heard - /play and /search included,
#: since they add to the session of whoever is listening.
STEERING_COMMANDS = {
    "play",
    "search",
    "shuffle",
    "clear",
    "volume",
    "seek",
    "loop",
    "remove",
    "move",
    "skip",
    "pause",
    "resume",
    "stop",
    "autoplay",
}
#: Read-only commands anyone may use.
LOOKING_COMMANDS = {"now", "queue"}


def guild_with_bot_in(channel_id: int = 77):
    guild = make_guild()
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    guild.voice_client = MagicMock(channel=channel)
    return guild, channel


def member_in(guild, channel, *, admin=False):
    member = make_member(
        5,
        guild=guild,
        permissions=discord.Permissions.all() if admin else discord.Permissions.none(),
    )
    member.voice = MagicMock(channel=channel) if channel is not None else None
    return member


def test_a_listener_may_steer() -> None:
    guild, channel = guild_with_bot_in()
    assert bot_voice_refusal(member_in(guild, channel)) is None


def test_someone_in_another_channel_may_not() -> None:
    guild, _ = guild_with_bot_in()
    other = MagicMock(spec=discord.VoiceChannel)
    refusal = bot_voice_refusal(member_in(guild, other))
    assert refusal is not None and "<#77>" in refusal


def test_someone_in_no_channel_may_not() -> None:
    guild, _ = guild_with_bot_in()
    assert bot_voice_refusal(member_in(guild, None)) is not None


def test_an_admin_may_always_stop_a_stuck_bot() -> None:
    guild, _ = guild_with_bot_in()
    assert bot_voice_refusal(member_in(guild, None, admin=True)) is None


def test_with_the_bot_out_of_voice_there_is_nothing_to_protect() -> None:
    guild = make_guild()
    guild.voice_client = None
    assert bot_voice_refusal(member_in(guild, None)) is None


@pytest.fixture
async def music_commands(tmp_path, make_settings):
    from core.bot import MusicBot

    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "v.db")))
    await bot.db.connect()
    await bot.load_extension("cogs.music")
    try:
        yield {c.name: c for c in bot.get_cog("Music").walk_app_commands()}
    finally:
        await bot.db.close()


def _has_voice_check(command) -> bool:
    return any("in_bot_voice" in check.__qualname__ for check in command.checks)


async def test_every_steering_command_checks_the_voice_channel(music_commands) -> None:
    missing = sorted(n for n in STEERING_COMMANDS if not _has_voice_check(music_commands[n]))
    assert not missing, f"steering without the voice check: {missing}"


async def test_looking_needs_no_voice_channel(music_commands) -> None:
    assert not any(_has_voice_check(music_commands[n]) for n in LOOKING_COMMANDS)


async def test_no_music_command_is_unclassified(music_commands) -> None:
    """A new command must be put in one list or the other."""
    assert set(music_commands) == STEERING_COMMANDS | LOOKING_COMMANDS
