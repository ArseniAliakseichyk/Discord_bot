"""Async SQLite storage (aiosqlite).

Stores: authorized guilds (private-bot whitelist), per-guild settings, and saved
sessions + queues so playback can be restored after a restart.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Literal

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS authorized_guilds (
    guild_id  INTEGER PRIMARY KEY,
    added_by  INTEGER,
    added_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id           INTEGER PRIMARY KEY,
    dj_role_id         INTEGER,
    command_channel_id INTEGER,
    default_volume     INTEGER
);

CREATE TABLE IF NOT EXISTS player_sessions (
    guild_id         INTEGER PRIMARY KEY,
    voice_channel_id INTEGER NOT NULL,
    text_channel_id  INTEGER
);

CREATE TABLE IF NOT EXISTS saved_queues (
    guild_id  INTEGER NOT NULL,
    position  INTEGER NOT NULL,
    uri       TEXT    NOT NULL,
    requester TEXT,
    avatar    TEXT,
    PRIMARY KEY (guild_id, position)
);
"""

class _Unset(Enum):
    """Sentinel for "argument not supplied" that type checkers understand.

    A bare ``object()`` would widen the parameter type to ``object`` and silently
    accept anything; ``Literal[_Unset.token]`` keeps the real types checkable.
    """

    token = 0


_UNSET = _Unset.token
OptionalId = int | None | Literal[_Unset.token]


@dataclass
class GuildSettings:
    guild_id: int
    dj_role_id: int | None = None
    command_channel_id: int | None = None
    default_volume: int | None = None


@dataclass
class SavedTrack:
    uri: str
    requester: str | None = None
    avatar: str | None = None


@dataclass
class PlayerSession:
    guild_id: int
    voice_channel_id: int
    text_channel_id: int | None


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._settings_cache: dict[int, GuildSettings] = {}
        self._authorized_cache: set[int] | None = None

    async def connect(self) -> None:
        """Open the connection and apply the schema. Safe to call twice."""
        if self._conn is not None:  # already connected — don't leak the old handle
            return
        # mkdir is a blocking syscall; keep it off the event loop.
        await asyncio.to_thread(Path(self.path).parent.mkdir, parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        # WAL keeps external readers (e.g. the sqlite3 CLI) from hitting "database
        # is locked"; busy_timeout covers the write lock.
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.executescript(SCHEMA)  # executescript commits implicitly
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        # Drop the caches too, otherwise a later connect() serves data from the
        # previous database file.
        self._settings_cache.clear()
        self._authorized_cache = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Commit on success, roll back on failure.

        Without the rollback a failed multi-statement write leaves the shared
        connection mid-transaction, and the next commit() from any other method
        would flush those partial statements.
        """
        conn = self.conn
        try:
            yield conn
        except BaseException:
            await conn.rollback()
            raise
        await conn.commit()

    # ------------------------------------------------------------------ #
    #  Authorized guilds
    # ------------------------------------------------------------------ #
    async def authorized_guilds(self) -> frozenset[int]:
        """Return the whitelist. Frozen so callers cannot corrupt the cache."""
        if self._authorized_cache is None:
            async with self.conn.execute("SELECT guild_id FROM authorized_guilds") as cur:
                rows = await cur.fetchall()
            self._authorized_cache = {row["guild_id"] for row in rows}
        return frozenset(self._authorized_cache)

    async def is_authorized(self, guild_id: int) -> bool:
        return guild_id in await self.authorized_guilds()

    async def authorize_guild(self, guild_id: int, added_by: int | None) -> bool:
        """Return True if the guild was newly added."""
        if await self.is_authorized(guild_id):
            return False
        async with self._transaction() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO authorized_guilds (guild_id, added_by, added_at) "
                "VALUES (?, ?, ?)",
                (guild_id, added_by, int(time.time())),
            )
        if self._authorized_cache is not None:
            self._authorized_cache.add(guild_id)
        return True

    async def deauthorize_guild(self, guild_id: int) -> bool:
        async with self._transaction() as conn:
            cur = await conn.execute(
                "DELETE FROM authorized_guilds WHERE guild_id = ?", (guild_id,)
            )
        if self._authorized_cache is not None:
            self._authorized_cache.discard(guild_id)
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    #  Guild settings
    # ------------------------------------------------------------------ #
    async def get_settings(self, guild_id: int) -> GuildSettings:
        """Return the guild's settings.

        Always a copy: callers must not be able to mutate the cache in place.
        """
        cached = self._settings_cache.get(guild_id)
        if cached is not None:
            return replace(cached)
        async with self.conn.execute(
            "SELECT dj_role_id, command_channel_id, default_volume "
            "FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        settings = GuildSettings(
            guild_id=guild_id,
            dj_role_id=row["dj_role_id"] if row else None,
            command_channel_id=row["command_channel_id"] if row else None,
            default_volume=row["default_volume"] if row else None,
        )
        self._settings_cache[guild_id] = settings
        return replace(settings)

    async def update_settings(
        self,
        guild_id: int,
        *,
        dj_role_id: OptionalId = _UNSET,
        command_channel_id: OptionalId = _UNSET,
        default_volume: OptionalId = _UNSET,
    ) -> GuildSettings:
        """Apply the supplied fields. The cache is updated only after the write."""
        current = await self.get_settings(guild_id)
        updated = replace(
            current,
            dj_role_id=current.dj_role_id if dj_role_id is _UNSET else dj_role_id,
            command_channel_id=(
                current.command_channel_id
                if command_channel_id is _UNSET
                else command_channel_id
            ),
            default_volume=(
                current.default_volume if default_volume is _UNSET else default_volume
            ),
        )
        async with self._transaction() as conn:
            await conn.execute(
                """INSERT INTO guild_settings
                       (guild_id, dj_role_id, command_channel_id, default_volume)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       dj_role_id         = excluded.dj_role_id,
                       command_channel_id = excluded.command_channel_id,
                       default_volume     = excluded.default_volume""",
                (
                    guild_id,
                    updated.dj_role_id,
                    updated.command_channel_id,
                    updated.default_volume,
                ),
            )
        self._settings_cache[guild_id] = updated
        return replace(updated)

    # ------------------------------------------------------------------ #
    #  Sessions and saved queues (for restart recovery)
    # ------------------------------------------------------------------ #
    async def save_session(
        self,
        guild_id: int,
        voice_channel_id: int,
        text_channel_id: int | None,
        tracks: list[SavedTrack],
    ) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """INSERT INTO player_sessions (guild_id, voice_channel_id, text_channel_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       voice_channel_id = excluded.voice_channel_id,
                       text_channel_id  = excluded.text_channel_id""",
                (guild_id, voice_channel_id, text_channel_id),
            )
            await conn.execute("DELETE FROM saved_queues WHERE guild_id = ?", (guild_id,))
            if tracks:
                await conn.executemany(
                    "INSERT INTO saved_queues (guild_id, position, uri, requester, avatar) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (guild_id, i, t.uri, t.requester, t.avatar)
                        for i, t in enumerate(tracks)
                    ],
                )

    async def load_sessions(self) -> list[PlayerSession]:
        async with self.conn.execute(
            "SELECT guild_id, voice_channel_id, text_channel_id FROM player_sessions"
        ) as cur:
            rows = await cur.fetchall()
        return [
            PlayerSession(
                guild_id=row["guild_id"],
                voice_channel_id=row["voice_channel_id"],
                text_channel_id=row["text_channel_id"],
            )
            for row in rows
        ]

    async def load_queue(self, guild_id: int) -> list[SavedTrack]:
        async with self.conn.execute(
            "SELECT uri, requester, avatar FROM saved_queues "
            "WHERE guild_id = ? ORDER BY position",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            SavedTrack(uri=row["uri"], requester=row["requester"], avatar=row["avatar"])
            for row in rows
        ]

    async def clear_session(self, guild_id: int) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                "DELETE FROM player_sessions WHERE guild_id = ?", (guild_id,)
            )
            await conn.execute("DELETE FROM saved_queues WHERE guild_id = ?", (guild_id,))
