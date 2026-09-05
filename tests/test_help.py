"""/help is generated from the live command tree.

The version this replaced was a hand-written list that had drifted: it named
commands that did not exist and omitted ones that did. These tests pin the
property that made the rewrite worthwhile - the page cannot disagree with the
tree - and the permission filtering that keeps a regular member from being
offered moderation commands they cannot run.
"""

from __future__ import annotations

import discord
import pytest
from discord import app_commands

from core.bot import INITIAL_EXTENSIONS, MusicBot
from tests.interaction_harness import make_guild, make_member


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "help.db")))
    await instance.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await instance.load_extension(extension)
    try:
        yield instance
    finally:
        await instance.db.close()


def member_with(permissions: discord.Permissions):
    guild = make_guild()
    return make_member(1, guild=guild, permissions=permissions)


def advertised(pages) -> set[str]:
    """Every command name the help pages mention."""
    names: set[str] = set()
    for page in pages.values():
        for line in page.body.splitlines():
            if line.startswith("**/"):
                names.add(line.split("**")[1].removeprefix("/"))
    return names


class TestGeneratedFromTheTree:
    async def test_never_advertises_a_command_that_does_not_exist(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.all()))
        registered = {
            command.qualified_name
            for command in bot.tree.walk_commands()
            if not isinstance(command, app_commands.Group)
        }
        assert advertised(pages) <= registered, (
            f"help lists commands the bot does not have: "
            f"{advertised(pages) - registered}"
        )

    async def test_an_administrator_sees_every_category(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.all()))
        from cogs.help import CATEGORIES

        loaded = {name for name in CATEGORIES if bot.get_cog(name) is not None}
        # Owner-only commands carry no default_permissions, so they show too.
        assert set(pages) <= loaded
        assert {"Music", "Voice", "Tickets", "Moderation"} <= set(pages)

    async def test_every_page_lists_something(self, bot) -> None:
        """An empty category would render a heading with nothing under it."""
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.all()))
        assert all(page.body.strip() for page in pages.values())

    async def test_music_page_covers_the_restored_commands(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.all()))
        music = pages["Music"].body
        for command in ("play", "seek", "loop", "volume", "remove", "move"):
            assert f"**/{command}**" in music, f"/{command} missing from the help page"


class TestPermissionFiltering:
    async def test_a_plain_member_is_not_offered_moderation(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.none()))
        assert "Moderation" not in pages
        assert not any(name.startswith("mod ") for name in advertised(pages))

    async def test_a_moderator_is_offered_moderation(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(
            member_with(discord.Permissions(moderate_members=True))
        )
        assert "Moderation" in pages

    async def test_ticket_configuration_needs_manage_guild(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        plain = advertised(help_cog.build_pages(member_with(discord.Permissions.none())))
        assert not any(name.startswith("ticket config") for name in plain)

        manager = advertised(
            help_cog.build_pages(member_with(discord.Permissions(manage_guild=True)))
        )
        assert any(name.startswith("ticket config") for name in manager)

    async def test_a_plain_member_still_sees_music(self, bot) -> None:
        help_cog = bot.get_cog("Help")
        pages = help_cog.build_pages(member_with(discord.Permissions.none()))
        assert "Music" in pages and "**/play**" in pages["Music"].body

    async def test_a_non_member_gets_only_ungated_commands(self, bot) -> None:
        """In a DM the invoker is a User, not a Member, with no permissions."""
        help_cog = bot.get_cog("Help")
        user = discord.User.__new__(discord.User)
        pages = help_cog.build_pages(user)
        assert "Moderation" not in pages


class TestCategoriesMatchTheCogs:
    async def test_every_category_names_a_loaded_cog(self, bot) -> None:
        """A renamed cog would silently drop its page from the menu."""
        from cogs.help import CATEGORIES

        missing = [name for name in CATEGORIES if bot.get_cog(name) is None]
        assert not missing, f"help references cogs that are not loaded: {missing}"

    async def test_every_command_carrying_cog_has_a_category(self, bot) -> None:
        from cogs.help import CATEGORIES

        with_commands = {
            command.binding.__class__.__name__
            for command in bot.tree.walk_commands()
            if getattr(command, "binding", None) is not None
        }
        uncategorised = with_commands - set(CATEGORIES) - {"Help"}
        assert not uncategorised, (
            f"these cogs have commands but no help page: {uncategorised}"
        )
