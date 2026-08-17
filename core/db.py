"""Async SQLite storage (aiosqlite).

Stores: authorized guilds (private-bot whitelist), per-guild settings, saved
sessions + queues so playback can be restored after a restart, the ticket
system's configuration and open tickets, and moderation warnings.

Every new feature gets its own table rather than extra columns on an existing
one, so ``CREATE TABLE IF NOT EXISTS`` is enough and a database created by an
older build keeps working without a migration step.
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

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id         INTEGER PRIMARY KEY,
    category_id      INTEGER,
    support_role_id  INTEGER,
    verify_role_id   INTEGER,
    log_channel_id   INTEGER,
    rules_text       TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
    guild_id   INTEGER NOT NULL,
    number     INTEGER NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    owner_id   INTEGER NOT NULL,
    claimed_by INTEGER,
    -- open | claimed | closed
    status     TEXT    NOT NULL DEFAULT 'open',
    category   TEXT,
    subject    TEXT,
    created_at INTEGER NOT NULL,
    closed_at  INTEGER,
    PRIMARY KEY (guild_id, number)
);

CREATE TABLE IF NOT EXISTS mod_config (
    guild_id           INTEGER PRIMARY KEY,
    mod_log_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason       TEXT,
    created_at   INTEGER NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_warnings_lookup
    ON warnings (guild_id, user_id, active);
"""

class _Unset(Enum):
    """Sentinel for "argument not supplied" that type checkers understand.

    A bare ``object()`` would widen the parameter type to ``object`` and silently
    accept anything; ``Literal[_Unset.token]`` keeps the real types checkable.
    """

    token = 0


_UNSET = _Unset.token
OptionalId = int | None | Literal[_Unset.token]
OptionalStr = str | None | Literal[_Unset.token]


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


@dataclass
class TicketConfig:
    guild_id: int
    category_id: int | None = None
    support_role_id: int | None = None
    verify_role_id: int | None = None
    log_channel_id: int | None = None
    rules_text: str | None = None

    @property
    def tickets_ready(self) -> bool:
        """Whether a ticket can actually be opened on this guild."""
        return self.category_id is not None and self.support_role_id is not None


@dataclass
class Ticket:
    guild_id: int
    number: int
    channel_id: int
    owner_id: int
    claimed_by: int | None
    status: str
    category: str | None
    subject: str | None
    created_at: int
    closed_at: int | None


@dataclass
class Warning_:
    """A moderation warning.

    Named with a trailing underscore so it cannot be confused with the builtin
    ``Warning`` exception at a glance in tracebacks or imports.
    """

    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str | None
    created_at: int
    active: bool


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._settings_cache: dict[int, GuildSettings] = {}
        self._authorized_cache: set[int] | None = None
        # Serialises write transactions over the single shared connection; see
        # _transaction() for why this is required rather than merely careful.
        self._write_lock = asyncio.Lock()

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
        """Run a write transaction: commit on success, roll back on failure.

        The lock is load-bearing, not defensive. Every caller shares one
        connection, and a connection can only be inside one transaction at a
        time — but each ``await`` inside a transaction hands control to another
        coroutine, which would then read half-applied state, or commit its own
        work and flush ours with it. Serialising writes is what makes a
        multi-statement transaction here actually atomic.

        Read-only helpers deliberately do not take the lock: SQLite in WAL mode
        serves them from the snapshot without blocking.
        """
        async with self._write_lock:
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

    # ------------------------------------------------------------------ #
    #  Ticket system configuration
    # ------------------------------------------------------------------ #
    # Deliberately uncached, unlike guild_settings: this is read on panel
    # button presses rather than on every command, so a cache would buy
    # nothing and add an invalidation path that can go stale.
    async def get_ticket_config(self, guild_id: int) -> TicketConfig:
        async with self.conn.execute(
            "SELECT category_id, support_role_id, verify_role_id, log_channel_id, "
            "rules_text FROM ticket_config WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return TicketConfig(guild_id=guild_id)
        return TicketConfig(
            guild_id=guild_id,
            category_id=row["category_id"],
            support_role_id=row["support_role_id"],
            verify_role_id=row["verify_role_id"],
            log_channel_id=row["log_channel_id"],
            rules_text=row["rules_text"],
        )

    async def update_ticket_config(
        self,
        guild_id: int,
        *,
        category_id: OptionalId = _UNSET,
        support_role_id: OptionalId = _UNSET,
        verify_role_id: OptionalId = _UNSET,
        log_channel_id: OptionalId = _UNSET,
        rules_text: OptionalStr = _UNSET,
    ) -> TicketConfig:
        current = await self.get_ticket_config(guild_id)
        updated = replace(
            current,
            category_id=(
                current.category_id if category_id is _UNSET else category_id
            ),
            support_role_id=(
                current.support_role_id if support_role_id is _UNSET else support_role_id
            ),
            verify_role_id=(
                current.verify_role_id if verify_role_id is _UNSET else verify_role_id
            ),
            log_channel_id=(
                current.log_channel_id if log_channel_id is _UNSET else log_channel_id
            ),
            rules_text=current.rules_text if rules_text is _UNSET else rules_text,
        )
        async with self._transaction() as conn:
            await conn.execute(
                """INSERT INTO ticket_config
                       (guild_id, category_id, support_role_id, verify_role_id,
                        log_channel_id, rules_text)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       category_id     = excluded.category_id,
                       support_role_id = excluded.support_role_id,
                       verify_role_id  = excluded.verify_role_id,
                       log_channel_id  = excluded.log_channel_id,
                       rules_text      = excluded.rules_text""",
                (
                    guild_id,
                    updated.category_id,
                    updated.support_role_id,
                    updated.verify_role_id,
                    updated.log_channel_id,
                    updated.rules_text,
                ),
            )
        return replace(updated)

    # ------------------------------------------------------------------ #
    #  Tickets
    # ------------------------------------------------------------------ #
    async def create_ticket(
        self,
        *,
        guild_id: int,
        channel_id: int,
        owner_id: int,
        category: str | None,
        subject: str | None,
    ) -> Ticket:
        """Allocate the next per-guild ticket number and store the ticket.

        The number is picked inside the same transaction as the insert, so two
        users pressing the button simultaneously cannot be handed the same one
        (the old implementation read and rewrote a plain text file, which
        could).
        """
        now = int(time.time())
        async with self._transaction() as conn:
            async with conn.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 AS next FROM tickets "
                "WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            number = row["next"] if row else 1
            await conn.execute(
                """INSERT INTO tickets
                       (guild_id, number, channel_id, owner_id, claimed_by,
                        status, category, subject, created_at, closed_at)
                   VALUES (?, ?, ?, ?, NULL, 'open', ?, ?, ?, NULL)""",
                (guild_id, number, channel_id, owner_id, category, subject, now),
            )
        return Ticket(
            guild_id=guild_id,
            number=number,
            channel_id=channel_id,
            owner_id=owner_id,
            claimed_by=None,
            status="open",
            category=category,
            subject=subject,
            created_at=now,
            closed_at=None,
        )

    async def get_ticket_by_channel(self, channel_id: int) -> Ticket | None:
        async with self.conn.execute(
            """SELECT guild_id, number, channel_id, owner_id, claimed_by, status,
                      category, subject, created_at, closed_at
               FROM tickets WHERE channel_id = ?""",
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return Ticket(
            guild_id=row["guild_id"],
            number=row["number"],
            channel_id=row["channel_id"],
            owner_id=row["owner_id"],
            claimed_by=row["claimed_by"],
            status=row["status"],
            category=row["category"],
            subject=row["subject"],
            created_at=row["created_at"],
            closed_at=row["closed_at"],
        )

    async def claim_ticket(self, channel_id: int, moderator_id: int) -> bool:
        """Mark the ticket claimed. False if it was already claimed or closed."""
        async with self._transaction() as conn:
            cur = await conn.execute(
                "UPDATE tickets SET status = 'claimed', claimed_by = ? "
                "WHERE channel_id = ? AND status = 'open'",
                (moderator_id, channel_id),
            )
        return cur.rowcount > 0

    async def close_ticket(self, channel_id: int) -> bool:
        """Mark the ticket closed. False if it was already closed or unknown."""
        async with self._transaction() as conn:
            cur = await conn.execute(
                "UPDATE tickets SET status = 'closed', closed_at = ? "
                "WHERE channel_id = ? AND status != 'closed'",
                (int(time.time()), channel_id),
            )
        return cur.rowcount > 0

    async def delete_ticket(self, channel_id: int) -> None:
        """Drop the row entirely — used when the ticket channel is deleted."""
        async with self._transaction() as conn:
            await conn.execute("DELETE FROM tickets WHERE channel_id = ?", (channel_id,))

    async def open_tickets_for(self, guild_id: int, owner_id: int) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS n FROM tickets "
            "WHERE guild_id = ? AND owner_id = ? AND status != 'closed'",
            (guild_id, owner_id),
        ) as cur:
            row = await cur.fetchone()
        return row["n"] if row else 0

    # ------------------------------------------------------------------ #
    #  Moderation
    # ------------------------------------------------------------------ #
    async def get_mod_log_channel(self, guild_id: int) -> int | None:
        async with self.conn.execute(
            "SELECT mod_log_channel_id FROM mod_config WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        return row["mod_log_channel_id"] if row else None

    async def set_mod_log_channel(self, guild_id: int, channel_id: int | None) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """INSERT INTO mod_config (guild_id, mod_log_channel_id)
                   VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                       mod_log_channel_id = excluded.mod_log_channel_id""",
                (guild_id, channel_id),
            )

    async def add_warning(
        self, guild_id: int, user_id: int, moderator_id: int, reason: str | None
    ) -> Warning_:
        now = int(time.time())
        async with self._transaction() as conn:
            cur = await conn.execute(
                """INSERT INTO warnings
                       (guild_id, user_id, moderator_id, reason, created_at, active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (guild_id, user_id, moderator_id, reason, now),
            )
            warning_id = cur.lastrowid or 0
        return Warning_(
            id=warning_id,
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=moderator_id,
            reason=reason,
            created_at=now,
            active=True,
        )

    async def list_warnings(
        self, guild_id: int, user_id: int, *, active_only: bool = True
    ) -> list[Warning_]:
        query = (
            "SELECT id, moderator_id, reason, created_at, active FROM warnings "
            "WHERE guild_id = ? AND user_id = ?"
        )
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY created_at DESC"
        async with self.conn.execute(query, (guild_id, user_id)) as cur:
            rows = await cur.fetchall()
        return [
            Warning_(
                id=row["id"],
                guild_id=guild_id,
                user_id=user_id,
                moderator_id=row["moderator_id"],
                reason=row["reason"],
                created_at=row["created_at"],
                active=bool(row["active"]),
            )
            for row in rows
        ]

    async def deactivate_warning(self, guild_id: int, warning_id: int) -> bool:
        """Scoped by guild so one server cannot clear another server's warning."""
        async with self._transaction() as conn:
            cur = await conn.execute(
                "UPDATE warnings SET active = 0 "
                "WHERE id = ? AND guild_id = ? AND active = 1",
                (warning_id, guild_id),
            )
        return cur.rowcount > 0

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        async with self._transaction() as conn:
            cur = await conn.execute(
                "UPDATE warnings SET active = 0 "
                "WHERE guild_id = ? AND user_id = ? AND active = 1",
                (guild_id, user_id),
            )
        return cur.rowcount
