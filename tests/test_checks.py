from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import GuildSettings
from utils.checks import user_is_dj


def make_member(*, admin=False, manage=False, role_ids=()):
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=admin, manage_guild=manage),
        roles=[SimpleNamespace(id=r) for r in role_ids],
        guild=SimpleNamespace(id=1),
    )


def make_bot(dj_role_id):
    return SimpleNamespace(
        db=SimpleNamespace(
            get_settings=AsyncMock(
                return_value=GuildSettings(guild_id=1, dj_role_id=dj_role_id)
            )
        )
    )


async def test_admin_always_dj():
    assert await user_is_dj(make_bot(99), make_member(admin=True))


async def test_no_dj_role_allows_everyone():
    assert await user_is_dj(make_bot(None), make_member())


async def test_dj_role_required():
    assert not await user_is_dj(make_bot(50), make_member(role_ids=[1, 2]))
    assert await user_is_dj(make_bot(50), make_member(role_ids=[50, 2]))
