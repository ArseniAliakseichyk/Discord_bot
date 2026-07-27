"""Allowed-mentions must reflect the invoker's permissions, not the bot's."""

from __future__ import annotations

from types import SimpleNamespace

import discord

from utils.mentions import mentions_for_free_text, mentions_for_role


def make_channel(perms: discord.Permissions) -> SimpleNamespace:
    return SimpleNamespace(permissions_for=lambda _user: perms)


def make_role(name: str, *, mentionable: bool) -> SimpleNamespace:
    return SimpleNamespace(name=name, mentionable=mentionable, id=hash(name) & 0xFFFF)


PRIVILEGED = discord.Permissions(mention_everyone=True)
PLAIN = discord.Permissions(send_messages=True)


def member() -> discord.Member:
    """A Member instance without running __init__.

    The helpers only need ``isinstance(user, discord.Member)`` to hold; every
    permission answer comes from the channel stub.
    """
    return discord.Member.__new__(discord.Member)


class TestMentionsForRole:
    def test_plain_user_cannot_ping_everyone(self) -> None:
        allowed = mentions_for_role(member(), make_channel(PLAIN), None)
        assert allowed.everyone is False

    def test_plain_user_cannot_ping_a_non_mentionable_role(self) -> None:
        role = make_role("Staff", mentionable=False)
        allowed = mentions_for_role(member(), make_channel(PLAIN), role)
        assert allowed.everyone is False
        assert allowed.roles is False

    def test_plain_user_may_ping_a_mentionable_role(self) -> None:
        role = make_role("Players", mentionable=True)
        allowed = mentions_for_role(member(), make_channel(PLAIN), role)
        assert allowed.roles == [role]

    def test_privileged_user_may_ping_anything(self) -> None:
        role = make_role("Staff", mentionable=False)
        allowed = mentions_for_role(member(), make_channel(PRIVILEGED), role)
        assert allowed.everyone is True
        assert allowed.roles == [role]


class TestMentionsForFreeText:
    def test_plain_user_gets_only_already_mentionable_roles(self) -> None:
        open_role = make_role("Players", mentionable=True)
        locked_role = make_role("Staff", mentionable=False)
        guild = SimpleNamespace(roles=[open_role, locked_role])
        allowed = mentions_for_free_text(member(), make_channel(PLAIN), guild)
        assert allowed.everyone is False
        assert allowed.roles == [open_role]

    def test_privileged_user_keeps_full_reach(self) -> None:
        guild = SimpleNamespace(roles=[make_role("Staff", mentionable=False)])
        allowed = mentions_for_free_text(member(), make_channel(PRIVILEGED), guild)
        assert allowed.everyone is True
        assert allowed.roles is True
