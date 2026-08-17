"""Ticket and warning storage.

Ticket numbering used to live in a plain text file shared by every guild, so two
users pressing the button at the same time could be handed the same number.
Allocation now happens inside the insert transaction.
"""

from __future__ import annotations

import asyncio

import pytest

from core.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "tickets.db"))
    await database.connect()
    yield database
    await database.close()


class TestTicketConfig:
    async def test_defaults_are_empty_and_not_ready(self, db: Database) -> None:
        config = await db.get_ticket_config(1)
        assert config.category_id is None
        assert config.tickets_ready is False

    async def test_ready_requires_category_and_support_role(self, db: Database) -> None:
        await db.update_ticket_config(1, category_id=10)
        assert (await db.get_ticket_config(1)).tickets_ready is False
        await db.update_ticket_config(1, support_role_id=20)
        assert (await db.get_ticket_config(1)).tickets_ready is True

    async def test_partial_update_keeps_other_fields(self, db: Database) -> None:
        await db.update_ticket_config(1, category_id=10, rules_text="hello")
        await db.update_ticket_config(1, verify_role_id=30)
        config = await db.get_ticket_config(1)
        assert (config.category_id, config.rules_text, config.verify_role_id) == (
            10,
            "hello",
            30,
        )

    async def test_explicit_none_clears_a_field(self, db: Database) -> None:
        await db.update_ticket_config(1, category_id=10)
        await db.update_ticket_config(1, category_id=None)
        assert (await db.get_ticket_config(1)).category_id is None

    async def test_guilds_are_isolated(self, db: Database) -> None:
        await db.update_ticket_config(1, category_id=10)
        assert (await db.get_ticket_config(2)).category_id is None


class TestTicketNumbering:
    async def test_numbers_increment_per_guild(self, db: Database) -> None:
        first = await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        second = await db.create_ticket(
            guild_id=1, channel_id=101, owner_id=5, category=None, subject=None
        )
        assert (first.number, second.number) == (1, 2)

    async def test_each_guild_starts_from_one(self, db: Database) -> None:
        await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        other = await db.create_ticket(
            guild_id=2, channel_id=200, owner_id=5, category=None, subject=None
        )
        assert other.number == 1

    async def test_concurrent_creation_never_reuses_a_number(self, db: Database) -> None:
        """The old file-based counter could hand out duplicates here."""
        tickets = await asyncio.gather(
            *(
                db.create_ticket(
                    guild_id=1,
                    channel_id=1000 + i,
                    owner_id=5,
                    category=None,
                    subject=None,
                )
                for i in range(20)
            )
        )
        numbers = [ticket.number for ticket in tickets]
        assert sorted(numbers) == list(range(1, 21))

    async def test_numbers_do_not_regress_after_a_delete(self, db: Database) -> None:
        await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        second = await db.create_ticket(
            guild_id=1, channel_id=101, owner_id=5, category=None, subject=None
        )
        await db.delete_ticket(second.channel_id)
        third = await db.create_ticket(
            guild_id=1, channel_id=102, owner_id=5, category=None, subject=None
        )
        assert third.number == 2  # highest surviving number was 1


class TestTicketLifecycle:
    async def test_claim_then_close(self, db: Database) -> None:
        ticket = await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category="bug", subject="s"
        )
        assert await db.claim_ticket(ticket.channel_id, 9) is True
        stored = await db.get_ticket_by_channel(100)
        assert stored is not None
        assert (stored.status, stored.claimed_by) == ("claimed", 9)
        assert await db.close_ticket(100) is True
        stored = await db.get_ticket_by_channel(100)
        assert stored is not None and stored.status == "closed"

    async def test_double_claim_is_rejected(self, db: Database) -> None:
        await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        assert await db.claim_ticket(100, 9) is True
        assert await db.claim_ticket(100, 8) is False

    async def test_closed_ticket_cannot_be_claimed(self, db: Database) -> None:
        await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        await db.close_ticket(100)
        assert await db.claim_ticket(100, 9) is False

    async def test_double_close_is_rejected(self, db: Database) -> None:
        await db.create_ticket(
            guild_id=1, channel_id=100, owner_id=5, category=None, subject=None
        )
        assert await db.close_ticket(100) is True
        assert await db.close_ticket(100) is False

    async def test_unknown_channel_returns_none(self, db: Database) -> None:
        assert await db.get_ticket_by_channel(4242) is None

    async def test_open_count_excludes_closed(self, db: Database) -> None:
        for channel_id in (100, 101, 102):
            await db.create_ticket(
                guild_id=1,
                channel_id=channel_id,
                owner_id=5,
                category=None,
                subject=None,
            )
        assert await db.open_tickets_for(1, 5) == 3
        await db.close_ticket(101)
        assert await db.open_tickets_for(1, 5) == 2
        assert await db.open_tickets_for(1, 6) == 0


class TestWarnings:
    async def test_add_and_list(self, db: Database) -> None:
        await db.add_warning(1, 5, 9, "spam")
        await db.add_warning(1, 5, 9, "flood")
        assert len(await db.list_warnings(1, 5)) == 2

    async def test_deactivate_hides_from_the_active_list(self, db: Database) -> None:
        warning = await db.add_warning(1, 5, 9, "spam")
        assert await db.deactivate_warning(1, warning.id) is True
        assert await db.list_warnings(1, 5) == []
        assert len(await db.list_warnings(1, 5, active_only=False)) == 1

    async def test_another_guild_cannot_clear_a_warning(self, db: Database) -> None:
        warning = await db.add_warning(1, 5, 9, "spam")
        assert await db.deactivate_warning(2, warning.id) is False
        assert len(await db.list_warnings(1, 5)) == 1

    async def test_deactivating_twice_is_rejected(self, db: Database) -> None:
        warning = await db.add_warning(1, 5, 9, "spam")
        await db.deactivate_warning(1, warning.id)
        assert await db.deactivate_warning(1, warning.id) is False

    async def test_clear_returns_the_count(self, db: Database) -> None:
        for _ in range(3):
            await db.add_warning(1, 5, 9, "x")
        assert await db.clear_warnings(1, 5) == 3
        assert await db.clear_warnings(1, 5) == 0

    async def test_warnings_are_scoped_per_user(self, db: Database) -> None:
        await db.add_warning(1, 5, 9, "a")
        await db.add_warning(1, 6, 9, "b")
        assert len(await db.list_warnings(1, 5)) == 1


class TestModConfig:
    async def test_unset_by_default(self, db: Database) -> None:
        assert await db.get_mod_log_channel(1) is None

    async def test_set_and_clear(self, db: Database) -> None:
        await db.set_mod_log_channel(1, 777)
        assert await db.get_mod_log_channel(1) == 777
        await db.set_mod_log_channel(1, None)
        assert await db.get_mod_log_channel(1) is None
