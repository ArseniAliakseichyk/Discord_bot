"""Moderation guards and duration parsing.

The hierarchy guard is the safety-critical part: without it a moderator with the
right Discord permission but a low role could try to act on an administrator,
and every such command failed with a bare Forbidden traceback.
"""

from __future__ import annotations

from datetime import timedelta

import discord
import pytest

from utils.moderation import (
    MAX_TIMEOUT,
    check_target,
    format_duration_ru,
    parse_duration,
)


class FakeRole:
    def __init__(self, position: int) -> None:
        self.position = position

    def __le__(self, other: FakeRole) -> bool:
        return self.position <= other.position

    def __lt__(self, other: FakeRole) -> bool:
        return self.position < other.position


class FakeGuild:
    def __init__(self, owner_id: int, me: FakeMember) -> None:
        self.owner_id = owner_id
        self.me = me


class FakeMember:
    def __init__(
        self,
        member_id: int,
        role_position: int,
        *,
        permissions: discord.Permissions | None = None,
    ) -> None:
        self.id = member_id
        self.top_role = FakeRole(role_position)
        self.mention = f"<@{member_id}>"
        # `permissions or Permissions.all()` would be wrong: Permissions.none()
        # is falsy, so an explicitly empty permission set would be replaced by
        # a full one and the test would silently assert nothing.
        self.guild_permissions = (
            discord.Permissions.all() if permissions is None else permissions
        )
        self.guild: FakeGuild = None  # type: ignore[assignment]


def scenario(
    *,
    moderator_role: int = 10,
    target_role: int = 5,
    bot_role: int = 50,
    owner_id: int = 999,
    bot_permissions: discord.Permissions | None = None,
) -> tuple[FakeMember, FakeMember]:
    bot = FakeMember(1, bot_role, permissions=bot_permissions)
    guild = FakeGuild(owner_id, bot)
    moderator = FakeMember(2, moderator_role)
    target = FakeMember(3, target_role)
    for member in (bot, moderator, target):
        member.guild = guild
    return moderator, target


class TestCheckTarget:
    def test_allows_a_normal_action(self) -> None:
        moderator, target = scenario()
        assert check_target(moderator, target, bot_permission="ban_members") is None

    def test_rejects_self(self) -> None:
        moderator, _ = scenario()
        problem = check_target(moderator, moderator, bot_permission=None)
        assert problem is not None and "к себе" in problem

    def test_rejects_the_bot(self) -> None:
        moderator, target = scenario()
        problem = check_target(moderator, target.guild.me, bot_permission=None)
        assert problem is not None and "к боту" in problem

    def test_rejects_the_guild_owner(self) -> None:
        moderator, target = scenario()
        target.id = target.guild.owner_id
        problem = check_target(moderator, target, bot_permission=None)
        assert problem is not None and "владельцу" in problem

    def test_rejects_a_target_of_equal_rank(self) -> None:
        moderator, target = scenario(moderator_role=10, target_role=10)
        problem = check_target(moderator, target, bot_permission=None)
        assert problem is not None and "не ниже вашей" in problem

    def test_rejects_a_higher_target(self) -> None:
        moderator, target = scenario(moderator_role=5, target_role=20)
        problem = check_target(moderator, target, bot_permission=None)
        assert problem is not None and "не ниже вашей" in problem

    def test_guild_owner_outranks_everyone(self) -> None:
        moderator, target = scenario(moderator_role=1, target_role=40, bot_role=50)
        moderator.id = target.guild.owner_id
        assert check_target(moderator, target, bot_permission=None) is None

    def test_rejects_when_the_target_outranks_the_bot(self) -> None:
        moderator, target = scenario(moderator_role=90, target_role=60, bot_role=50)
        problem = check_target(moderator, target, bot_permission=None)
        assert problem is not None and "выше роли бота" in problem

    def test_reports_a_missing_bot_permission_by_name(self) -> None:
        moderator, target = scenario(bot_permissions=discord.Permissions.none())
        problem = check_target(moderator, target, bot_permission="ban_members")
        assert problem is not None and "Банить участников" in problem

    def test_permission_is_checked_before_hierarchy(self) -> None:
        """The missing-permission message is the more actionable one."""
        moderator, target = scenario(
            moderator_role=1, target_role=40, bot_permissions=discord.Permissions.none()
        )
        problem = check_target(moderator, target, bot_permission="kick_members")
        assert problem is not None and "Выгонять участников" in problem


class TestParseDuration:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("30s", timedelta(seconds=30)),
            ("10m", timedelta(minutes=10)),
            ("2h", timedelta(hours=2)),
            ("1d", timedelta(days=1)),
            ("1w", timedelta(weeks=1)),
            ("1h30m", timedelta(hours=1, minutes=30)),
            ("10", timedelta(minutes=10)),  # bare number reads as minutes
            ("  2H  ", timedelta(hours=2)),
        ],
    )
    def test_valid(self, text: str, expected: timedelta) -> None:
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["", "abc", "10x", "m", "-5m", "10 minutes"])
    def test_invalid(self, text: str) -> None:
        assert parse_duration(text) is None

    def test_partial_junk_is_rejected_not_silently_truncated(self) -> None:
        """"10xyz" must not quietly become 10 minutes."""
        assert parse_duration("10xyz") is None

    def test_the_discord_cap_is_representable(self) -> None:
        assert parse_duration("28d") == MAX_TIMEOUT


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(seconds=30), "30с"),
            (timedelta(minutes=10), "10мин"),
            (timedelta(hours=1, minutes=30), "1ч 30мин"),
            (timedelta(days=2), "2д"),
            (timedelta(0), "0с"),
        ],
    )
    def test_render(self, delta: timedelta, expected: str) -> None:
        assert format_duration_ru(delta) == expected
