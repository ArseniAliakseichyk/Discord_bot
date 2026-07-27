import pytest
import pytest_asyncio

from core.db import Database, SavedTrack


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_authorize_and_deauthorize(db):
    assert not await db.is_authorized(1)
    assert await db.authorize_guild(1, 100) is True
    assert await db.authorize_guild(1, 100) is False  # already authorized
    assert await db.is_authorized(1)
    assert await db.deauthorize_guild(1) is True
    assert await db.deauthorize_guild(1) is False
    assert not await db.is_authorized(1)


async def test_settings_partial_update_preserves_other_fields(db):
    assert (await db.get_settings(5)).dj_role_id is None
    await db.update_settings(5, dj_role_id=42)
    await db.update_settings(5, default_volume=80)
    settings = await db.get_settings(5)
    assert settings.dj_role_id == 42  # preserved across updates
    assert settings.default_volume == 80
    assert settings.command_channel_id is None


async def test_session_and_queue_roundtrip(db):
    tracks = [
        SavedTrack("https://x/1", "me", "avatar"),
        SavedTrack("https://x/2", None, None),
    ]
    await db.save_session(7, voice_channel_id=1234, text_channel_id=5678, tracks=tracks)

    sessions = await db.load_sessions()
    assert len(sessions) == 1
    assert sessions[0].guild_id == 7
    assert sessions[0].voice_channel_id == 1234
    assert sessions[0].text_channel_id == 5678

    loaded = await db.load_queue(7)
    assert [t.uri for t in loaded] == ["https://x/1", "https://x/2"]
    assert loaded[0].requester == "me"

    await db.clear_session(7)
    assert await db.load_sessions() == []
    assert await db.load_queue(7) == []


async def test_get_settings_returns_a_copy_not_the_cache(db):
    """Mutating the returned object must not corrupt the in-process cache."""
    first = await db.get_settings(11)
    first.dj_role_id = 999
    second = await db.get_settings(11)
    assert second.dj_role_id is None


async def test_update_settings_result_is_detached_from_the_cache(db):
    returned = await db.update_settings(12, dj_role_id=5)
    returned.dj_role_id = 777
    assert (await db.get_settings(12)).dj_role_id == 5


async def test_failed_write_leaves_cache_and_disk_in_agreement(db, monkeypatch):
    await db.update_settings(13, dj_role_id=1)

    original_execute = db.conn.execute
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if "INSERT INTO guild_settings" in args[0]:
            raise RuntimeError("disk full")
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(db.conn, "execute", flaky)
    with pytest.raises(RuntimeError):
        await db.update_settings(13, dj_role_id=2)
    monkeypatch.undo()

    # The cache must still show the last successfully persisted value.
    assert (await db.get_settings(13)).dj_role_id == 1


async def test_save_session_rolls_back_on_failure(db):
    """A failed executemany must not leave a staged DELETE for a later commit."""
    await db.save_session(20, 1, 1, [SavedTrack("https://x/keep")])

    original = db.conn.executemany

    async def boom(*args, **kwargs):
        raise RuntimeError("write failed")

    db.conn.executemany = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await db.save_session(20, 1, 1, [SavedTrack("https://x/new")])
    db.conn.executemany = original  # type: ignore[method-assign]

    # An unrelated commit must not flush the rolled-back DELETE.
    await db.update_settings(21, dj_role_id=1)
    assert [t.uri for t in await db.load_queue(20)] == ["https://x/keep"]


async def test_authorized_guilds_is_immutable(db):
    await db.authorize_guild(30, None)
    guilds = await db.authorized_guilds()
    assert isinstance(guilds, frozenset)
    assert guilds == {30}


async def test_connect_is_idempotent(db):
    conn_before = db.conn
    await db.connect()  # must not replace (and leak) the open connection
    assert db.conn is conn_before


async def test_close_clears_caches(tmp_path):
    path = str(tmp_path / "reuse.db")
    database = Database(path)
    await database.connect()
    await database.authorize_guild(40, None)
    await database.update_settings(40, dj_role_id=7)
    await database.close()

    # Same object, fresh database file: stale cache entries must not survive.
    database.path = str(tmp_path / "other.db")
    await database.connect()
    try:
        assert await database.authorized_guilds() == frozenset()
        assert (await database.get_settings(40)).dj_role_id is None
    finally:
        await database.close()
