"""/join, /jointo and /leave against the real player."""

from __future__ import annotations

from typing import Any

from tests.interaction_harness import FakeInteraction, idle_text
from tests.lavalink_stand import Stand
from tests.test_now_playing_panel import listener


async def _run(stand: Stand, command: str, *args: Any, user: Any = None) -> Any:
    voice = stand.bot.get_cog("Voice")
    interaction = FakeInteraction(
        user=user or listener(stand), guild=stand.guild, channel=stand.home
    )
    await getattr(voice, command).callback(voice, interaction, *args)
    await stand.lavalink.settle()
    return interaction.record


async def test_leave_retires_the_panel_and_names_who(stand) -> None:
    await stand.play("a", "b")
    panel = stand.music.now_messages[stand.gid]
    record = await _run(stand, "leave", user=listener(stand, 6))
    assert "отключён — user6" in (idle_text(panel) or "")
    assert stand.gid in stand.lavalink.destroyed
    assert record.messages[0]["ephemeral"] is True
    assert len(stand.home.sent) == 1, "no second message for one event"


async def test_leave_forgets_the_saved_session(stand) -> None:
    await stand.play("a", "b")
    await _run(stand, "leave")
    assert await stand.bot.db.load_sessions() == []


async def test_leave_and_jointo_check_the_voice_channel(stand) -> None:
    voice = stand.bot.get_cog("Voice")
    commands = {c.name: c for c in voice.walk_app_commands()}
    for name in ("leave", "jointo"):
        assert any("in_bot_voice" in c.__qualname__ for c in commands[name].checks), name
