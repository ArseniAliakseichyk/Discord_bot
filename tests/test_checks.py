from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from core.db import GuildSettings
from utils.checks import (
    MissingAnnouncePerms,
    MissingDJRole,
    NotAuthorized,
    NotOwner,
    WrongChannel,
    can_announce,
    guild_authorized,
    has_dj,
    in_command_channel,
    is_owner,
    user_is_dj,
)


class FakeMember(discord.Member):
    """A real ``discord.Member`` subclass, since the checks use isinstance().

    ``__init__`` of the base class is deliberately not called; the three
    attributes the checks read are overridden as properties (the originals are
    computed properties on Member and would otherwise win over instance state).
    """

    def __init__(self, *, admin=False, manage=False, role_ids=(), guild_id=1):
        self._perms = discord.Permissions(administrator=admin, manage_guild=manage)
        self._role_ids = tuple(role_ids)
        self._fake_guild = SimpleNamespace(id=guild_id)

    @property
    def guild_permissions(self):
        return self._perms

    @property
    def roles(self):
        return [SimpleNamespace(id=r) for r in self._role_ids]

    @property
    def guild(self):
        return self._fake_guild


def make_member(*, admin=False, manage=False, role_ids=()):
    return FakeMember(admin=admin, manage=manage, role_ids=role_ids)


def make_bot(dj_role_id):
    return SimpleNamespace(
        db=SimpleNamespace(
            get_settings=AsyncMock(
                return_value=GuildSettings(guild_id=1, dj_role_id=dj_role_id)
            )
        )
    )


async def test_admin_always_dj():
    assert await user_is_dj(make_bot(99), make_member(admin=True))


async def test_no_dj_role_allows_everyone():
    assert await user_is_dj(make_bot(None), make_member())


async def test_dj_role_required():
    assert not await user_is_dj(make_bot(50), make_member(role_ids=[1, 2]))
    assert await user_is_dj(make_bot(50), make_member(role_ids=[50, 2]))


def make_interaction(bot, *, guild_id=1, member=None, channel_id=10):
    return SimpleNamespace(
        client=bot,
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        user=member,
        channel_id=channel_id,
    )


async def run_check(decorator, interaction):
    """Invoke the predicate a check factory wrapped, without a real Command."""
    holder = SimpleNamespace(__discord_app_commands_checks__=[])
    decorator(holder)
    (predicate,) = holder.__discord_app_commands_checks__
    return await predicate(interaction)


class TestGuildAuthorized:
    async def test_rejects_direct_messages(self):
        bot = SimpleNamespace(db=SimpleNamespace(is_authorized=AsyncMock(return_value=True)))
        with pytest.raises(NotAuthorized):
            await run_check(guild_authorized(), make_interaction(bot, guild_id=None))

    async def test_allows_a_whitelisted_guild(self):
        bot = SimpleNamespace(db=SimpleNamespace(is_authorized=AsyncMock(return_value=True)))
        assert await run_check(guild_authorized(), make_interaction(bot)) is True

    async def test_rejects_an_unlisted_guild(self):
        bot = SimpleNamespace(db=SimpleNamespace(is_authorized=AsyncMock(return_value=False)))
        with pytest.raises(NotAuthorized):
            await run_check(guild_authorized(), make_interaction(bot))


class TestIsOwner:
    async def test_allows_the_owner(self):
        bot = SimpleNamespace(is_owner=AsyncMock(return_value=True))
        assert await run_check(is_owner(), make_interaction(bot)) is True

    async def test_rejects_everyone_else(self):
        bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
        with pytest.raises(NotOwner):
            await run_check(is_owner(), make_interaction(bot))


class TestHasDj:
    async def test_rejects_a_member_without_the_dj_role(self):
        member = make_member(role_ids=[7])
        with pytest.raises(MissingDJRole):
            await run_check(has_dj(), make_interaction(make_bot(50), member=member))


class TestInCommandChannel:
    def _bot(self, channel_id):
        return SimpleNamespace(
            db=SimpleNamespace(
                get_settings=AsyncMock(
                    return_value=GuildSettings(guild_id=1, command_channel_id=channel_id)
                )
            )
        )

    async def test_unrestricted_when_no_channel_is_configured(self):
        member = make_member()
        interaction = make_interaction(self._bot(None), member=member)
        assert await run_check(in_command_channel(), interaction) is True

    async def test_allows_the_configured_channel(self):
        member = make_member()
        interaction = make_interaction(self._bot(10), member=member, channel_id=10)
        assert await run_check(in_command_channel(), interaction) is True

    async def test_rejects_other_channels_and_reports_the_right_one(self):
        member = make_member()
        interaction = make_interaction(self._bot(10), member=member, channel_id=99)
        with pytest.raises(WrongChannel) as excinfo:
            await run_check(in_command_channel(), interaction)
        assert excinfo.value.channel_id == 10
        assert "10" in str(excinfo.value)  # message is populated, not empty

    async def test_admins_bypass_the_restriction(self):
        member = make_member(admin=True)
        interaction = make_interaction(self._bot(10), member=member, channel_id=99)
        assert await run_check(in_command_channel(), interaction) is True


class TestCanAnnounce:
    def _bot(self, allowed_roles):
        return SimpleNamespace(settings=SimpleNamespace(announce_allowed_roles=allowed_roles))

    async def test_rejects_direct_messages(self):
        with pytest.raises(MissingAnnouncePerms):
            await run_check(can_announce(), make_interaction(self._bot(set()), guild_id=None))

    async def test_admin_is_allowed(self):
        member = make_member(admin=True)
        interaction = make_interaction(self._bot(set()), member=member)
        assert await run_check(can_announce(), interaction) is True

    async def test_allowed_role_is_enough(self):
        member = make_member(role_ids=[77])
        interaction = make_interaction(self._bot({77}), member=member)
        assert await run_check(can_announce(), interaction) is True

    async def test_other_members_are_rejected(self):
        member = make_member(role_ids=[5])
        interaction = make_interaction(self._bot({77}), member=member)
        with pytest.raises(MissingAnnouncePerms):
            await run_check(can_announce(), interaction)
