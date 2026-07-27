"""Smoke test: every module imports and every cog loads.

A broken import in a single cog used to leave the bot running with a partial
command tree, which the unconditional tree.sync() then pushed to Discord —
deregistering the missing slash commands. This catches that at test time.
"""

from __future__ import annotations

import importlib

import pytest

from core.bot import INITIAL_EXTENSIONS, MusicBot

MODULES = [
    "bot",
    "config",
    "core.bot",
    "core.constants",
    "core.db",
    "core.lavalink",
    "ui.controls",
    "ui.search",
    "ui.views",
    "utils.checks",
    "utils.formatting",
    "utils.logging",
    "utils.mentions",
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
    "now",
    "pause",
    "play",
    "queue",
    "resume",
    "search",
    "servers",
    "settings",
    "settings channel",
    "settings djrole",
    "settings show",
    "settings volume",
    "shuffle",
    "skip",
    "stop",
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


async def test_now_playing_view_has_no_method_shadowing() -> None:
    """The stop button must not overwrite discord.ui.View.stop()."""
    from discord.ui import View

    from ui.controls import NowPlayingControls

    assert NowPlayingControls.stop is View.stop
