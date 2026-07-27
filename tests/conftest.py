"""Shared fixtures.

``Settings`` reads both the process environment and the repository's ``.env``.
Tests must depend on neither, so environment variables are cleared here and
``make_settings`` disables the ``.env`` file explicitly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from config import Settings

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
