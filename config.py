"""Typed bot configuration.

All environment variables are read and validated here once, at startup. If a
required variable is missing or has the wrong type, the bot exits with a clear
error before connecting to Discord (see ``bot.py``).
"""

from __future__ import annotations

from functools import lru_cache

import discord
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_id_set(value: object) -> set[int]:
    """Parse a set of IDs from a ``"1, 2, 3"`` string or an existing collection."""
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        return {int(x.strip()) for x in value.split(",") if x.strip().isdigit()}
    if isinstance(value, (set, list, tuple)):
        return {int(x) for x in value}
    return value  # type: ignore[return-value]


class Settings(BaseSettings):
    """Configuration assembled from environment variables and the ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Discord ---
    discord_token: str = Field(..., alias="DISCORD_TOKEN")
    owner_ids: set[int] = Field(default_factory=set, alias="OWNER_IDS")
    log_channel_id: int | None = Field(default=None, alias="LOG_CHANNEL_ID")
    excluded_user_ids: set[int] = Field(default_factory=set, alias="EXCLUDED_USER_IDS")

    # --- Lavalink ---
    lavalink_uri: str = Field(default="http://lavalink:2333", alias="LAVALINK_URI")
    lavalink_password: str = Field(default="youshallnotpass", alias="LAVALINK_PASSWORD")
    # Directory where Lavalink sees the local music folder (mounted in compose).
    lavalink_local_dir: str = Field(default="/music", alias="LAVALINK_LOCAL_DIR")

    # --- Announcements / roles ---
    announce_default_channel: int | None = Field(default=None, alias="DEFAULT_CHANNEL")
    announce_allowed_roles: set[int] = Field(default_factory=set, alias="ALLOWED_ROLES")
    announce_color: int = 0x2B2D31

    # --- Music ---
    music_folder: str = Field(default="./music", alias="MUSIC_FOLDER")
    max_track_length: int = Field(default=1200, alias="MAX_TRACK_LENGTH")  # seconds
    max_playlist_tracks: int = Field(default=100, alias="MAX_PLAYLIST_TRACKS")
    default_volume: int = Field(default=100, alias="DEFAULT_VOLUME")  # 0..200
    inactive_timeout: int = Field(default=300, alias="INACTIVE_TIMEOUT")  # seconds

    # --- Storage ---
    database_path: str = Field(default="./data/bot.db", alias="DATABASE_PATH")

    @field_validator(
        "owner_ids", "excluded_user_ids", "announce_allowed_roles", mode="before"
    )
    @classmethod
    def _ids(cls, v: object) -> set[int]:
        return _parse_id_set(v)

    @field_validator("default_volume")
    @classmethod
    def _clamp_volume(cls, v: int) -> int:
        return max(0, min(v, 200))

    @property
    def intents(self) -> discord.Intents:
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: needed by builder/logging
        intents.members = True  # privileged: needed for member join/leave logs
        intents.voice_states = True
        return intents


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (lazy initialization)."""
    return Settings()  # type: ignore[call-arg]
