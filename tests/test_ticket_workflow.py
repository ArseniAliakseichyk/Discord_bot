"""Opening, claiming and closing tickets under the conditions Discord imposes.

Discord allows two renames per channel per ten minutes, and discord.py waits
out a rate limit inside the call that hit it. The ticket workflow used to
rename three times, so a quick claim-then-close froze the Close button.
"""

from __future__ import annotations

import asyncio
from itertools import count
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.tickets import MAX_OPEN_TICKETS
from core.bot import MusicBot
from tests.interaction_harness import (
    FakeInteraction,
    drive,
    find_item,
    make_channel,
    make_guild,
    make_member,
    make_role,
)
from ui.tickets import CID_CLAIM, CID_CLOSE, TicketControls

_channel_ids = count(5000)


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "tickets.db")))
    await instance.db.connect()
    await instance.load_extension("cogs.tickets")
    try:
        yield instance
    finally:
        cog = instance.get_cog("Tickets")
        for task in list(cog._renamers.values()):
            task.cancel()
        await instance.db.close()


def ticket_guild():
    guild = make_guild()
    support = make_role(300, position=5, name="Support")
    category = MagicMock(spec=discord.CategoryChannel)
    category.id = 1
    category.channels = []
    guild.get_role = lambda _id: support
    guild.get_channel = lambda cid: category if cid == 1 else None
    guild.default_role = make_role(guild.id, position=0, name="@everyone")
    created: list[discord.TextChannel] = []

    async def create_text_channel(name, **_kwargs):
        await asyncio.sleep(0)  # an HTTP call
        channel = make_channel(next(_channel_ids), guild=guild)
        channel.name = name
        created.append(channel)
        return channel

    guild.create_text_channel = AsyncMock(side_effect=create_text_channel)
    return guild, support, created


def followup_text(record) -> str:
    """Everything said in followups, including inside v2 panels."""
    parts = []
    for followup in record.followups:
        parts.append(followup.get("content") or "")
        view = followup.get("view")
        if view is not None:
            parts.extend(getattr(i, "content", "") for i in view.walk_children())
    return "\n".join(parts)


async def configure(bot, guild):
    await bot.db.update_ticket_config(guild.id, category_id=1, support_role_id=300)


async def submit(bot, guild, member, subject="тема"):
    cog = bot.get_cog("Tickets")
    interaction = FakeInteraction(user=member, guild=guild, channel=make_channel(guild=guild))
    await cog.open_ticket(interaction, category="question", subject=subject, body="текст")
    return interaction.record


async def test_the_channel_is_named_once_with_its_final_number(bot) -> None:
    guild, _, created = ticket_guild()
    await configure(bot, guild)
    await submit(bot, guild, make_member(10, guild=guild))
    assert len(created) == 1
    assert created[0].name.startswith("ticket-0001-")
    created[0].edit.assert_not_awaited()  # no rename spent on creation


async def test_simultaneous_tickets_get_distinct_numbers_matching_their_names(bot) -> None:
    guild, _, created = ticket_guild()
    await configure(bot, guild)
    members = [make_member(20 + i, guild=guild) for i in range(4)]
    await asyncio.gather(*(submit(bot, guild, m) for m in members))
    names = sorted(c.name[:11] for c in created)
    assert names == ["ticket-0001", "ticket-0002", "ticket-0003", "ticket-0004"]
    for channel in created:
        ticket = await bot.db.get_ticket_by_channel(channel.id)
        assert ticket is not None
        assert channel.name.startswith(f"ticket-{ticket.number:04d}")


async def test_the_open_ticket_limit_holds_when_several_forms_are_submitted(bot) -> None:
    """Opening the form five times and submitting each used to pass the limit."""
    guild, _, created = ticket_guild()
    await configure(bot, guild)
    member = make_member(30, guild=guild)
    records = await asyncio.gather(*(submit(bot, guild, member) for _ in range(5)))
    assert len(created) == MAX_OPEN_TICKETS
    refused = [r for r in records if "открытых обращений" in followup_text(r)]
    assert len(refused) == 5 - MAX_OPEN_TICKETS


async def test_close_does_not_wait_for_a_rate_limited_rename(bot) -> None:
    """The freeze: claim renames, then close's rename waits out Discord's limit."""
    guild, _, created = ticket_guild()
    await configure(bot, guild)
    owner = make_member(40, guild=guild)
    await submit(bot, guild, owner)
    channel = created[0]
    guild.get_member = lambda _id: owner

    release = asyncio.Event()
    names: list[str] = []

    async def edit(*, name: str, **_kwargs):
        names.append(name)
        await release.wait()  # discord.py sleeping out a 429
        channel.name = name

    channel.edit = AsyncMock(side_effect=edit)
    cog = bot.get_cog("Tickets")
    staff = make_member(41, guild=guild)  # Permissions.all(): counts as support

    for cid in (CID_CLAIM, CID_CLOSE):
        view = TicketControls(cog, number=1, owner=owner)
        interaction = FakeInteraction(
            user=staff, guild=guild, channel=channel, message=MagicMock(spec=discord.Message)
        )
        await asyncio.wait_for(drive(view, find_item(view, cid), interaction), timeout=2)
        assert interaction.record.acknowledged

    ticket = await bot.db.get_ticket_by_channel(channel.id)
    assert ticket is not None and ticket.status == "closed"

    release.set()
    for _ in range(50):
        await asyncio.sleep(0)
        if not cog._renamers:
            break
    assert names[0].startswith("claimed-")
    assert names[-1].startswith("closed-ticket-0001"), names
    assert len(names) == 2, "the rename that was overtaken must not run as well"
