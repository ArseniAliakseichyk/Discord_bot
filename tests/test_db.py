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
