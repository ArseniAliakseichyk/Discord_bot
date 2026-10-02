"""The /mod commands themselves, not only their helpers."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.moderation import PURGE_AUTHOR_SCAN
from core.bot import MusicBot
from tests.interaction_harness import FakeInteraction, make_channel, make_guild, make_member


@pytest.fixture
async def mod(tmp_path, make_settings):
    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "mod.db")))
    await bot.db.connect()
    await bot.load_extension("cogs.moderation")
    try:
        yield bot.get_cog("Moderation")
    finally:
        await bot.db.close()


def scene():
    guild = make_guild(bot_top_position=50)
    moderator = make_member(1, guild=guild, top_role_position=40)
    channel = make_channel(10, guild=guild)
    return guild, moderator, channel


def said(interaction: FakeInteraction) -> str:
    """Everything the moderator was told, including text inside v2 panels."""
    parts: list[str] = []
    for entry in (*interaction.record.messages, *interaction.record.followups):
        parts.append(entry.get("content") or "")
        view = entry.get("view")
        if view is not None:
            parts.extend(getattr(i, "content", "") for i in view.walk_children())
    return "\n".join(parts)


async def run(cog: Any, command: str, interaction: FakeInteraction, *args: Any) -> FakeInteraction:
    await getattr(cog, command).callback(cog, interaction, *args)
    return interaction


def departed_user(user_id: int = 77) -> Any:
    user = MagicMock(spec=discord.User)
    user.id = user_id
    user.mention = f"<@{user_id}>"
    user.send = AsyncMock()
    return user


# --------------------------------------------------------------------------- #
#  Ban
# --------------------------------------------------------------------------- #
async def test_someone_who_already_left_can_be_banned(mod) -> None:
    guild, moderator, channel = scene()
    target = departed_user()
    await run(
        mod, "ban", FakeInteraction(user=moderator, guild=guild, channel=channel), target, "raid", 1
    )
    guild.ban.assert_awaited_once()
    assert guild.ban.await_args.kwargs["delete_message_seconds"] == 86_400
    target.send.assert_not_awaited()  # no mutual server, no DM


@pytest.mark.parametrize("who", ["self", "bot", "owner"])
async def test_a_departed_user_ban_still_refuses_the_untouchables(mod, who) -> None:
    guild, moderator, channel = scene()
    ids = {"self": moderator.id, "bot": guild.me.id, "owner": guild.owner_id}
    interaction = await run(
        mod,
        "ban",
        FakeInteraction(user=moderator, guild=guild, channel=channel),
        departed_user(ids[who]),
        None,
        0,
    )
    guild.ban.assert_not_awaited()
    assert "нельзя" in said(interaction)


async def test_a_refused_ban_retracts_the_notice(mod) -> None:
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    guild.ban = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))
    await run(
        mod, "ban", FakeInteraction(user=moderator, guild=guild, channel=channel), target, None, 0
    )
    sent = [str(call) for call in target.send.await_args_list]
    assert len(sent) == 2, "the ban notice and then its correction"
    texts = [
        i.content
        for call in target.send.await_args_list
        for i in call.kwargs["view"].walk_children()
        if hasattr(i, "content")
    ]
    assert any("недействительно" in t for t in texts)


async def test_ban_uses_seconds_not_the_deprecated_days(mod) -> None:
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    await run(
        mod, "ban", FakeInteraction(user=moderator, guild=guild, channel=channel), target, None, 7
    )
    kwargs = guild.ban.await_args.kwargs
    assert "delete_message_days" not in kwargs
    assert kwargs["delete_message_seconds"] == 7 * 86_400


# --------------------------------------------------------------------------- #
#  Kick, timeouts
# --------------------------------------------------------------------------- #
async def test_a_refused_kick_retracts_the_notice(mod) -> None:
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    target.kick = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "x"))
    await run(
        mod, "kick", FakeInteraction(user=moderator, guild=guild, channel=channel), target, None
    )
    assert target.send.await_count == 2


async def test_unmute_of_an_expired_timeout_is_not_attempted(mod) -> None:
    """timed_out_until stays set after the timeout runs out."""
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    target.timed_out_until = discord.utils.utcnow() - datetime.timedelta(hours=1)
    target.is_timed_out = MagicMock(return_value=False)
    interaction = await run(
        mod, "unmute", FakeInteraction(user=moderator, guild=guild, channel=channel), target
    )
    target.timeout.assert_not_awaited()
    assert "нет активного тайм-аута" in said(interaction)


async def test_mute_rejects_more_than_discords_maximum(mod) -> None:
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    interaction = await run(
        mod,
        "mute",
        FakeInteraction(user=moderator, guild=guild, channel=channel),
        target,
        "30d",
        None,
    )
    target.timeout.assert_not_awaited()
    assert "28" in said(interaction)


# --------------------------------------------------------------------------- #
#  Purge
# --------------------------------------------------------------------------- #
def history(channel: Any, authors: list[int]) -> list[Any]:
    """Messages newest first, as purge sees them; wires channel.purge to them."""
    now = discord.utils.utcnow()
    messages = []
    for index, author in enumerate(authors):
        message = MagicMock(spec=discord.Message)
        message.author = MagicMock(id=author)
        message.created_at = now - datetime.timedelta(minutes=index)
        messages.append(message)

    async def purge(*, limit, check, **_kwargs):
        channel.scanned = limit
        return [m for m in messages[:limit] if check(m)]

    channel.purge = AsyncMock(side_effect=purge)
    return messages


async def test_purge_by_author_deletes_that_many_of_their_messages(mod) -> None:
    """It used to scan `count` messages and delete X's share - often none."""
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild)
    # The target wrote every tenth message.
    history(channel, [5 if i % 10 == 0 else 9 for i in range(200)])
    interaction = FakeInteraction(user=moderator, guild=guild, channel=channel)
    await run(mod, "purge", interaction, 10, target)
    assert channel.scanned == PURGE_AUTHOR_SCAN
    assert "**10**" in said(interaction)


async def test_purge_without_an_author_deletes_exactly_count(mod) -> None:
    guild, moderator, channel = scene()
    history(channel, [9] * 50)
    interaction = FakeInteraction(user=moderator, guild=guild, channel=channel)
    await run(mod, "purge", interaction, 5, None)
    assert channel.scanned == 5
    assert "**5**" in said(interaction)


async def test_purge_skips_messages_discord_cannot_bulk_delete(mod) -> None:
    guild, moderator, channel = scene()
    messages = history(channel, [9] * 10)
    for message in messages[5:]:
        message.created_at = discord.utils.utcnow() - datetime.timedelta(days=20)
    interaction = FakeInteraction(user=moderator, guild=guild, channel=channel)
    await run(mod, "purge", interaction, 10, None)
    assert "**5**" in said(interaction), "the count must be the real one"


async def test_purge_works_in_a_thread(mod) -> None:
    guild, moderator, _ = scene()
    thread = MagicMock(spec=discord.Thread)
    thread.permissions_for = MagicMock(return_value=discord.Permissions.all())
    thread.mention = "<#11>"
    history(thread, [9] * 3)
    interaction = FakeInteraction(user=moderator, guild=guild, channel=thread)
    await run(mod, "purge", interaction, 3, None)
    assert "**3**" in said(interaction)


# --------------------------------------------------------------------------- #
#  Warnings
# --------------------------------------------------------------------------- #
async def test_warn_records_and_counts(mod) -> None:
    guild, moderator, channel = scene()
    target = make_member(5, guild=guild, top_role_position=1)
    for _ in range(2):
        interaction = await run(
            mod,
            "warn",
            FakeInteraction(user=moderator, guild=guild, channel=channel),
            target,
            "spam",
        )
    assert "Активных: **2**" in said(interaction)
    assert len(await mod.bot.db.list_warnings(guild.id, target.id)) == 2


async def test_a_moderator_cannot_warn_someone_above_them(mod) -> None:
    guild, moderator, channel = scene()
    boss = make_member(5, guild=guild, top_role_position=45)
    interaction = await run(
        mod, "warn", FakeInteraction(user=moderator, guild=guild, channel=channel), boss, None
    )
    assert await mod.bot.db.list_warnings(guild.id, boss.id) == []
    assert "не ниже вашей" in said(interaction)
