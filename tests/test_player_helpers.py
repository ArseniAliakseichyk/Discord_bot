"""Shared player helpers that replaced three copy-pasted implementations."""

from __future__ import annotations

from types import SimpleNamespace

from core.db import GuildSettings
from utils.player import player_of, resolve_volume


class TestPlayerOf:
    def test_none_guild(self) -> None:
        assert player_of(None) is None

    def test_returns_the_voice_client(self) -> None:
        sentinel = object()
        guild = SimpleNamespace(voice_client=sentinel)
        assert player_of(guild) is sentinel  # type: ignore[arg-type]

    def test_no_voice_client(self) -> None:
        assert player_of(SimpleNamespace(voice_client=None)) is None  # type: ignore[arg-type]


class TestResolveVolume:
    def test_guild_override_wins(self) -> None:
        guild = GuildSettings(guild_id=1, default_volume=42)
        assert resolve_volume(guild, SimpleNamespace(default_volume=100)) == 42

    def test_falls_back_to_the_global_default(self) -> None:
        guild = GuildSettings(guild_id=1, default_volume=None)
        assert resolve_volume(guild, SimpleNamespace(default_volume=100)) == 100

    def test_zero_is_an_override_not_a_missing_value(self) -> None:
        guild = GuildSettings(guild_id=1, default_volume=0)
        assert resolve_volume(guild, SimpleNamespace(default_volume=100)) == 0
