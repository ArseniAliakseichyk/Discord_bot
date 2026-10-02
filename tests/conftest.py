"""Shared fixtures.

``Settings`` reads both the process environment and the repository's ``.env``.
Tests must depend on neither, so environment variables are cleared here and
``make_settings`` disables the ``.env`` file explicitly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from config import Settings
from tests.lavalink_stand import FakeLavalink, Stand, make_real_player

_ENV_KEYS = (
    "DISCORD_TOKEN",
    "OWNER_IDS",
    "LOG_CHANNEL_ID",
    "EXCLUDED_USER_IDS",
    "LAVALINK_URI",
    "LAVALINK_PASSWORD",
    "LAVALINK_LOCAL_DIR",
    "ALLOWED_ROLES",
    "DEFAULT_CHANNEL",
    "ANNOUNCE_COLOR",
    "MUSIC_FOLDER",
    "MAX_TRACK_LENGTH",
    "MAX_PLAYLIST_TRACKS",
    "DEFAULT_VOLUME",
    "INACTIVE_TIMEOUT",
    "DATABASE_PATH",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate every test from the developer's own shell exports."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build a ``Settings`` from explicit values, ignoring the on-disk .env."""

    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {"DISCORD_TOKEN": "test-token"}
        values.update(overrides)
        return Settings(_env_file=None, **values)  # type: ignore[arg-type]

    return factory


@pytest.fixture(params=["batched", "separate"])
async def stand(request, tmp_path, make_settings):
    """A bot with every cog, a real wavelink player and a scripted Lavalink.

    Runs each test twice: with Lavalink's events delivered in one batch and
    one at a time, the two orderings the network produces.
    """
    from core.bot import INITIAL_EXTENSIONS, MusicBot
    from tests.interaction_harness import make_guild, make_home_channel

    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "stand.db")))
    # What login() would do: bind the client to the running loop, which
    # dispatch() needs to schedule listeners.
    await bot._async_setup_hook()
    await bot.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await bot.load_extension(extension)
    lavalink = FakeLavalink(bot, separate=request.param == "separate")
    lavalink.start()
    guild = make_guild()
    player = make_real_player(bot, lavalink, guild)
    music = bot.get_cog("Music")
    home = make_home_channel()
    music.home_channels[guild.id] = home.id
    bot.get_channel = lambda cid: home if cid == home.id else None  # type: ignore[method-assign]

    # discord.py catches an exception in a listener and only logs it, so a
    # broken handler would otherwise look like a passing test.
    listener_errors: list[str] = []

    async def on_error(event: str, *args: Any, **kwargs: Any) -> None:
        import traceback

        listener_errors.append(f"{event}: {traceback.format_exc()}")

    bot.on_error = on_error  # type: ignore[method-assign]
    try:
        yield Stand(bot, music, lavalink, player, guild, home)
        await lavalink.settle()
        assert not listener_errors, "a listener raised:\n" + "\n".join(listener_errors)
    finally:
        await lavalink.stop()
        await bot.db.close()
