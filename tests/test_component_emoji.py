"""Every emoji on a button or select option must be one Discord accepts.

Discord rejects the whole message when one is not ("Invalid emoji"), so a
single bad character breaks the panel it sits on. "⇅" on the constructor's
field-order button did exactly that in production: /constructor failed every
time, and no test noticed, because nothing checked what Discord checks.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import emoji
import pytest
import wavelink

from core.bot import MusicBot
from tests.interaction_harness import make_guild, make_member

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("cogs", "core", "ui", "utils")


def _valid(name: str) -> bool:
    return emoji.is_emoji(name)


def _emoji_in(payload: Any) -> list[str]:
    """Unicode emoji names anywhere in a component payload."""
    found: list[str] = []
    if isinstance(payload, dict):
        value = payload.get("emoji")
        if isinstance(value, dict) and value.get("id") is None and value.get("name"):
            found.append(value["name"])
        for child in payload.values():
            found.extend(_emoji_in(child))
    elif isinstance(payload, list):
        for child in payload:
            found.extend(_emoji_in(child))
    return found


# --------------------------------------------------------------------------- #
#  Every literal in the source
# --------------------------------------------------------------------------- #
def _literal_emoji() -> list[tuple[str, int, str]]:
    """``emoji="..."`` arguments and ``x.emoji = ...`` assignments, with locations."""
    found: list[tuple[str, int, str]] = []
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                values: list[ast.expr] = []
                if isinstance(node, ast.keyword) and node.arg == "emoji":
                    values.append(node.value)
                elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and t.attr == "emoji" for t in node.targets
                ):
                    values.append(node.value)
                for value in values:
                    for constant in ast.walk(value):
                        if isinstance(constant, ast.Constant) and isinstance(constant.value, str):
                            rel = path.relative_to(ROOT).as_posix()
                            found.append((rel, constant.lineno, constant.value))
    return found


LITERALS = _literal_emoji()


def test_the_scan_finds_the_emoji_it_should() -> None:
    """Guard against the scan silently matching nothing."""
    assert len(LITERALS) > 20
    assert any(value == "↕️" for _, _, value in LITERALS)


@pytest.mark.parametrize(("path", "line", "value"), LITERALS)
def test_every_emoji_literal_is_a_real_emoji(path: str, line: int, value: str) -> None:
    assert _valid(value), f"{path}:{line}: {value!r} is not an emoji Discord accepts"


def test_the_checker_rejects_what_discord_rejected() -> None:
    assert not _valid("⇅")
    assert _valid("↕️")


# --------------------------------------------------------------------------- #
#  Every panel as it is actually sent
# --------------------------------------------------------------------------- #
@pytest.fixture
async def loaded_bot(tmp_path, make_settings):
    from core.bot import INITIAL_EXTENSIONS

    bot = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "emoji.db")))
    await bot.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await bot.load_extension(extension)
    try:
        yield bot
    finally:
        await bot.db.close()


def _rendered(bot: MusicBot) -> dict[str, Any]:
    from tests.test_interactions import all_views
    from ui.search import SearchView
    from ui.tickets import TicketModal

    guild = make_guild()
    member = make_member(1, guild=guild)
    payloads: dict[str, Any] = {name: view.to_components() for name, view in all_views(bot).items()}
    track = wavelink.Playable(
        {
            "encoded": "enc",
            "info": {
                "identifier": "x",
                "isSeekable": True,
                "author": "a",
                "length": 1000,
                "isStream": False,
                "position": 0,
                "title": "t",
                "uri": None,
                "sourceName": "youtube",
                "artworkUrl": None,
                "isrc": None,
            },
            "pluginInfo": {},
            "userData": {},
        }
    )
    payloads["search"] = SearchView(bot.get_cog("Music"), [track], member).to_components()
    payloads["ticket_modal"] = TicketModal(bot.get_cog("Tickets")).to_components()
    return payloads


async def test_every_panel_sends_only_valid_emoji(loaded_bot) -> None:
    bad = [
        f"{name}: {value!r}"
        for name, payload in _rendered(loaded_bot).items()
        for value in _emoji_in(payload)
        if not _valid(value)
    ]
    assert not bad, "Discord would reject these messages:\n" + "\n".join(bad)


async def test_the_live_panel_in_every_state_sends_valid_emoji(stand) -> None:
    from ui.controls import now_playing_panel

    await stand.play("a", "b")
    seen: list[str] = []
    for mode in wavelink.QueueMode:
        stand.player.queue.mode = mode
        for paused in (False, True):
            stand.player._paused = paused
            for radio in (False, True):
                (stand.music._radio.add if radio else stand.music._radio.discard)(stand.gid)
                view = now_playing_panel(stand.player.current, stand.player, stand.music)
                seen.extend(_emoji_in(view.to_components()))
    stand.player._paused = False
    stand.music._radio.discard(stand.gid)
    assert seen
    assert all(_valid(value) for value in seen), [v for v in seen if not _valid(v)]
