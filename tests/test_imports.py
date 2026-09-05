"""Smoke test: every module imports and every cog loads.

A broken import in a single cog used to leave the bot running with a partial
command tree, which the unconditional tree.sync() then pushed to Discord —
deregistering the missing slash commands. This catches that at test time.
"""

from __future__ import annotations

import importlib

import pytest
from discord import ui

from core.bot import INITIAL_EXTENSIONS, MusicBot

MODULES = [
    "bot",
    "config",
    "core.bot",
    "core.constants",
    "core.db",
    "core.lavalink",
    "ui.builder",
    "ui.builder.colors",
    "ui.builder.fields",
    "ui.builder.images",
    "ui.builder.modals",
    "ui.builder.panel",
    "ui.builder.rows",
    "ui.builder.state",
    "ui.controls",
    "ui.search",
    "ui.tickets",
    "ui.v2",
    "utils.checks",
    "utils.formatting",
    "utils.logging",
    "utils.mentions",
    "utils.moderation",
    "utils.player",
    "utils.validation",
    *INITIAL_EXTENSIONS,
]

#: Every slash command the bot is expected to register.
EXPECTED_COMMANDS = {
    "announce",
    "authorize",
    "autoplay",
    "clear",
    "constructor",
    "deauthorize",
    "help",
    "join",
    "jointo",
    "leave",
    "loop",
    "mod",
    "mod ban",
    "mod clearwarns",
    "mod kick",
    "mod log",
    "mod mute",
    "mod purge",
    "mod slowmode",
    "mod unban",
    "mod unmute",
    "mod unwarn",
    "mod warn",
    "mod warnings",
    "move",
    "now",
    "pause",
    "play",
    "queue",
    "remove",
    "resume",
    "search",
    "seek",
    "servers",
    "settings",
    "settings channel",
    "settings djrole",
    "settings show",
    "settings volume",
    "shuffle",
    "skip",
    "stop",
    "ticket",
    "ticket add",
    "ticket close",
    "ticket config",
    "ticket config category",
    "ticket config log",
    "ticket config rules",
    "ticket config show",
    "ticket config support-role",
    "ticket config verify-role",
    "ticket panel",
    "volume",
}


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)


async def test_all_cogs_load_and_register_their_commands(tmp_path, make_settings) -> None:
    settings = make_settings(DATABASE_PATH=str(tmp_path / "smoke.db"))
    bot = MusicBot(settings)
    await bot.db.connect()
    try:
        for extension in INITIAL_EXTENSIONS:
            await bot.load_extension(extension)
        registered = {command.qualified_name for command in bot.tree.walk_commands()}
        assert registered == EXPECTED_COMMANDS
    finally:
        await bot.db.close()


async def test_playback_controls_do_not_shadow_view_methods() -> None:
    """A button callback named `stop` would overwrite View.stop()."""
    from ui.controls import PlaybackControls

    assert not hasattr(PlaybackControls, "stop") or PlaybackControls.stop is ui.View.stop


async def test_persistent_panels_are_registered(tmp_path, make_settings) -> None:
    """Ticket and rules buttons must survive a restart.

    They only do so if the views are persistent (no timeout, explicit
    custom_ids) *and* registered with add_view during setup.
    """
    settings = make_settings(DATABASE_PATH=str(tmp_path / "views.db"))
    bot = MusicBot(settings)
    await bot.db.connect()
    try:
        await bot.load_extension("cogs.tickets")
        registered = {
            item.custom_id
            for view in bot.persistent_views
            for item in view.walk_children()
            if isinstance(item, ui.Button)
        }
        assert {
            "rules:verify",
            "rules:ticket",
            "rules:help",
            "ticket:claim",
            "ticket:close",
        } <= registered
        assert all(view.is_persistent() for view in bot.persistent_views)
    finally:
        await bot.db.close()
