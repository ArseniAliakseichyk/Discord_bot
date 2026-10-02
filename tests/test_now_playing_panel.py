"""The now-playing panel: what it shows and what each control does.

Controls are pressed through the same dispatch discord.py uses, against the
real wavelink Player and Queue on the scripted Lavalink (tests.lavalink_stand),
so a button test exercises what a listener in Discord would trigger.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import discord
import pytest
import wavelink
from discord import ui

from tests.interaction_harness import FakeInteraction, drive, find_item, idle_text, make_member
from tests.lavalink_stand import Stand, view_text
from ui.controls import (
    CID_BACK,
    CID_JUMP,
    CID_LOOP,
    CID_PLAY_PAUSE,
    CID_QUEUE,
    CID_SHUFFLE,
    CID_SKIP,
    CID_STOP,
    CID_VOLUME_DOWN,
    CID_VOLUME_UP,
    UP_NEXT_PREVIEW,
    VOLUME_MAX,
    VOLUME_STEP,
    now_playing_panel,
)
from ui.v2 import MAX_V2_COMPONENTS, V2_TEXT_LIMIT, count_components, text_length


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def listener(stand: Stand, member_id: int = 1, *, admin: bool = True) -> Any:
    """A member in the bot's voice channel; admins bypass the role checks."""
    member = make_member(
        member_id,
        guild=stand.guild,
        permissions=None if admin else discord.Permissions.none(),
    )
    member.voice = MagicMock(channel=stand.player.channel)
    return member


def outsider(stand: Stand, member_id: int = 2) -> Any:
    member = make_member(member_id, guild=stand.guild, permissions=discord.Permissions.none())
    member.voice = None
    return member


async def press(
    stand: Stand,
    key: str,
    *,
    user: Any = None,
    values: list[str] | None = None,
    view: Any = None,
) -> Any:
    view = view or stand.live_panel_view()
    item = find_item(view, key)
    interaction = FakeInteraction(
        user=user or listener(stand),
        guild=stand.guild,
        channel=stand.home,
        message=stand.music.now_messages.get(stand.gid),
        values=values,
    )
    record = await drive(view, item, interaction)
    await stand.lavalink.settle()
    return record


def panel_text(stand: Stand) -> str:
    return view_text(stand.live_panel_view())


def queued(stand: Stand) -> list[str]:
    return [t.title for t in stand.player.queue]


# --------------------------------------------------------------------------- #
#  What the panel shows
# --------------------------------------------------------------------------- #
class TestLayout:
    async def test_fits_discords_limits_with_a_huge_queue(self, stand) -> None:
        """40 components and 4000 characters, whatever is queued."""
        long = "Ж" * 95 + " *_[]()`~|>"
        await stand.play(long, *[f"{long}{i}" for i in range(120)])
        view = now_playing_panel(stand.player.current, stand.player, stand.music)
        assert count_components(view) <= MAX_V2_COMPONENTS
        assert text_length(view) <= V2_TEXT_LIMIT

    async def test_markdown_in_titles_is_escaped(self, stand) -> None:
        await stand.play("now", "**bold** [link](https://evil.example)")
        text = panel_text(stand)
        assert "\\*\\*bold\\*\\*" in text
        assert "\\[link\\]" in text, "a title must not become a clickable link"

    async def test_up_next_lists_the_first_tracks_and_counts_the_rest(self, stand) -> None:
        await stand.play("now", "n1", "n2", "n3", "n4", "n5")
        text = panel_text(stand)
        for title in ("n1", "n2", "n3"):
            assert title in text
        assert "n4" not in text.split("Далее")[1].split("-#")[0]
        assert f"ещё {5 - UP_NEXT_PREVIEW}" in text
        assert "в очереди 5" in text

    async def test_an_empty_queue_says_so_and_offers_no_jump_list(self, stand) -> None:
        await stand.play("only")
        assert "Очередь пуста" in panel_text(stand)
        with pytest.raises(LookupError):
            find_item(stand.live_panel_view(), CID_JUMP)

    async def test_the_jump_list_offers_the_queue_in_order(self, stand) -> None:
        await stand.play("now", "a", "b", "c")
        select = find_item(stand.live_panel_view(), CID_JUMP)
        assert [o.label for o in select.options] == ["1. a", "2. b", "3. c"]

    async def test_controls_that_would_do_nothing_are_disabled(self, stand) -> None:
        await stand.play("only")
        view = stand.live_panel_view()
        assert find_item(view, CID_SHUFFLE).disabled, "nothing to shuffle"
        assert find_item(view, CID_QUEUE).disabled, "nothing queued"
        assert not find_item(view, CID_SKIP).disabled

    async def test_volume_buttons_stop_at_the_limits(self, stand) -> None:
        await stand.play("only")
        await stand.player.set_volume(VOLUME_MAX)
        await stand.music.refresh_now_message(stand.player)
        assert find_item(stand.live_panel_view(), CID_VOLUME_UP).disabled
        await stand.player.set_volume(0)
        await stand.music.refresh_now_message(stand.player)
        assert find_item(stand.live_panel_view(), CID_VOLUME_DOWN).disabled

    async def test_the_play_pause_control_shows_the_action_it_performs(self, stand) -> None:
        await stand.play("only")
        assert str(find_item(stand.live_panel_view(), CID_PLAY_PAUSE).emoji) == "⏸️"
        await press(stand, CID_PLAY_PAUSE)
        assert str(find_item(stand.live_panel_view(), CID_PLAY_PAUSE).emoji) == "▶️"
        assert "На паузе" in panel_text(stand)

    async def test_the_last_action_and_its_author_are_shown(self, stand) -> None:
        await stand.play("only")
        await press(stand, CID_PLAY_PAUSE, user=listener(stand, 7))
        assert "⏸️ Пауза — user7" in panel_text(stand)


# --------------------------------------------------------------------------- #
#  Transport: ⏮ ⏯ ⏭ ⏹
# --------------------------------------------------------------------------- #
class TestBack:
    async def test_near_the_start_it_plays_the_previous_track(self, stand) -> None:
        await stand.play("first", "second")
        await stand.finish()  # "first" played through; "second" is on
        assert stand.lavalink.now(stand.gid) == "second"
        await press(stand, CID_BACK)
        assert stand.lavalink.now(stand.gid) == "first"
        assert queued(stand)[0] == "second", "the track we left must come next"

    async def test_skip_after_back_returns_to_where_we_were(self, stand) -> None:
        await stand.play("first", "second", "third")
        await stand.finish()
        await press(stand, CID_BACK)
        await press(stand, CID_SKIP)
        assert stand.lavalink.now(stand.gid) == "second"
        assert queued(stand) == ["third"]

    async def test_further_in_it_restarts_the_track(self, stand) -> None:
        await stand.play("first", "second")
        await stand.finish()
        stand.lavalink.report_position(stand.gid, 60_000)
        await stand.lavalink.settle()
        await press(stand, CID_BACK)
        assert stand.lavalink.now(stand.gid) == "second"
        assert stand.lavalink.guilds[stand.gid].seeks[-1] == 0

    async def test_with_no_history_it_restarts(self, stand) -> None:
        await stand.play("only")
        await press(stand, CID_BACK)
        assert stand.lavalink.now(stand.gid) == "only"
        assert stand.lavalink.guilds[stand.gid].seeks == [0]

    async def test_back_while_paused_plays_audibly(self, stand) -> None:
        await stand.play("first", "second")
        await stand.finish()
        await press(stand, CID_PLAY_PAUSE)
        await press(stand, CID_BACK)
        assert stand.lavalink.now(stand.gid) == "first"
        assert not stand.lavalink.guilds[stand.gid].paused

    async def test_back_does_not_duplicate_history(self, stand) -> None:
        await stand.play("first", "second")
        await stand.finish()
        await press(stand, CID_BACK)
        titles = [t.title for t in stand.player.queue.history]
        assert titles == ["first"]


class TestStop:
    async def test_stop_turns_the_panel_idle_and_names_who(self, stand) -> None:
        await stand.play("a", "b")
        panel = stand.music.now_messages[stand.gid]
        await press(stand, CID_STOP, user=listener(stand, 4))
        assert "остановлено — user4" in (idle_text(panel) or "")
        assert stand.lavalink.now(stand.gid) is None
        assert queued(stand) == []

    async def test_after_stop_the_next_play_posts_a_fresh_panel(self, stand) -> None:
        await stand.play("a")
        await press(stand, CID_STOP)
        await stand.play("b")
        live = [m for m in stand.panels() if idle_text(m) is None and not m.deleted]
        assert len(live) == 1


# --------------------------------------------------------------------------- #
#  Modes: 🔀 🔁 🔉 🔊 📜
# --------------------------------------------------------------------------- #
class TestModes:
    async def test_loop_cycles_like_spotify(self, stand) -> None:
        await stand.play("a")
        seen = []
        for _ in range(3):
            await press(stand, CID_LOOP)
            seen.append(stand.player.queue.mode)
        assert seen == [
            wavelink.QueueMode.loop_all,
            wavelink.QueueMode.loop,
            wavelink.QueueMode.normal,
        ]

    async def test_loop_button_shows_the_mode(self, stand) -> None:
        await stand.play("a")
        await press(stand, CID_LOOP)
        button = find_item(stand.live_panel_view(), CID_LOOP)
        assert button.style is discord.ButtonStyle.success and str(button.emoji) == "🔁"
        await press(stand, CID_LOOP)
        button = find_item(stand.live_panel_view(), CID_LOOP)
        assert str(button.emoji) == "🔂"

    async def test_volume_steps_and_redraws(self, stand) -> None:
        await stand.play("a")
        start = stand.player.volume
        record = await press(stand, CID_VOLUME_DOWN)
        assert stand.player.volume == start - VOLUME_STEP
        assert record.acks == ["edit_message"], "one call: answer and redraw"
        assert f"🔊 {start - VOLUME_STEP}%" in panel_text(stand)

    async def test_shuffle_keeps_the_same_tracks(self, stand) -> None:
        await stand.play("now", *[f"t{i}" for i in range(10)])
        await press(stand, CID_SHUFFLE)
        assert sorted(queued(stand)) == sorted(f"t{i}" for i in range(10))

    async def test_the_queue_is_shown_privately_to_anyone(self, stand) -> None:
        """Looking is not steering: no DJ role or voice channel needed."""
        await stand.play("now", "next")
        record = await press(stand, CID_QUEUE, user=outsider(stand))
        assert record.messages and record.messages[0].get("ephemeral") is True
        assert "next" in view_text(record.messages[0]["view"])


# --------------------------------------------------------------------------- #
#  Jumping ahead
# --------------------------------------------------------------------------- #
class TestJump:
    async def _options(self, stand) -> list[str]:
        return [o.value for o in find_item(stand.live_panel_view(), CID_JUMP).options]

    async def test_jump_plays_the_choice_and_drops_what_was_before(self, stand) -> None:
        await stand.play("now", "a", "b", "c")
        values = await self._options(stand)
        await press(stand, CID_JUMP, values=[values[1]])
        assert stand.lavalink.now(stand.gid) == "b"
        assert queued(stand) == ["c"]

    async def test_a_stale_panel_still_plays_the_track_that_was_shown(self, stand) -> None:
        await stand.play("now", "a", "b", "c")
        view = stand.live_panel_view()
        choice = find_item(view, CID_JUMP).options[2].value  # "c" at index 2
        stand.player.queue.delete(0)  # someone removed "a" meanwhile
        await press(stand, CID_JUMP, values=[choice], view=view)
        assert stand.lavalink.now(stand.gid) == "c"

    async def test_a_track_that_left_the_queue_is_not_guessed_at(self, stand) -> None:
        await stand.play("now", "a", "b")
        view = stand.live_panel_view()
        choice = find_item(view, CID_JUMP).options[1].value  # "b"
        stand.player.queue.delete(1)
        record = await press(stand, CID_JUMP, values=[choice], view=view)
        assert stand.lavalink.now(stand.gid) == "now"
        assert any("изменилась" in (f["content"] or "") for f in record.followups)

    async def test_under_repeat_queue_the_skipped_tracks_come_round_again(self, stand) -> None:
        stand.player.queue.mode = wavelink.QueueMode.loop_all
        await stand.play("now", "a", "b")
        values = await self._options(stand)
        await press(stand, CID_JUMP, values=[values[1]])
        history = [t.title for t in stand.player.queue.history]
        assert "a" in history


# --------------------------------------------------------------------------- #
#  Who may press
# --------------------------------------------------------------------------- #
STEERING = [CID_BACK, CID_PLAY_PAUSE, CID_SKIP, CID_STOP, CID_LOOP, CID_VOLUME_UP]


class TestPermissions:
    @pytest.mark.parametrize("key", STEERING)
    async def test_someone_outside_the_voice_channel_cannot_steer(self, stand, key) -> None:
        await stand.play("a", "b")
        before = (stand.lavalink.now(stand.gid), stand.player.paused, stand.player.queue.mode)
        record = await press(stand, key, user=outsider(stand))
        assert record.acks == ["send_message"]
        assert "голосовой канал" in record.messages[0]["content"]
        assert record.messages[0]["ephemeral"] is True
        after = (stand.lavalink.now(stand.gid), stand.player.paused, stand.player.queue.mode)
        assert after == before

    async def test_a_listener_without_admin_rights_may_steer(self, stand) -> None:
        await stand.play("a")
        await press(stand, CID_PLAY_PAUSE, user=listener(stand, admin=False))
        assert stand.player.paused

    async def test_hammering_the_buttons_is_slowed_down(self, stand) -> None:
        await stand.play("a")
        user = listener(stand, 3)
        records = [await press(stand, CID_LOOP, user=user) for _ in range(8)]
        refused = [r for r in records if r.messages and "Не так быстро" in r.messages[0]["content"]]
        assert len(refused) == 2  # BUTTON_RATE presses pass, the rest wait
        assert all(r.acknowledged for r in records)

    async def test_the_cooldown_is_per_user(self, stand) -> None:
        await stand.play("a")
        for _ in range(6):
            await press(stand, CID_LOOP, user=listener(stand, 3))
        record = await press(stand, CID_LOOP, user=listener(stand, 4))
        assert record.acks == ["edit_message"]


# --------------------------------------------------------------------------- #
#  Panels across restarts
# --------------------------------------------------------------------------- #
class TestRestart:
    async def test_the_live_panel_is_recorded(self, stand) -> None:
        await stand.play("a")
        message = stand.music.now_messages[stand.gid]
        assert await stand.bot.db.take_now_panels() == [(stand.gid, stand.home.id, message.id)]

    async def test_a_retired_panel_is_forgotten(self, stand) -> None:
        await stand.play("a")
        await stand.finish()
        assert await stand.bot.db.take_now_panels() == []

    async def test_startup_removes_panels_left_by_the_previous_process(self, stand) -> None:
        await stand.bot.db.save_now_panel(stand.gid, 55, 999)
        deleted: list[int] = []

        class Partial:
            def __init__(self, message_id: int) -> None:
                self.id = message_id

            async def delete(self) -> None:
                deleted.append(self.id)

        channel = MagicMock()
        channel.get_partial_message = Partial
        stand.bot.get_partial_messageable = lambda _cid: channel  # type: ignore[method-assign]
        await stand.music._remove_stale_panels()
        assert deleted == [999]
        assert await stand.bot.db.take_now_panels() == []

    async def test_a_press_on_an_unknown_panel_adopts_it(self, stand) -> None:
        """After a restart the old panel is in no dict; the next track must replace it."""
        await stand.play("a", "b")
        old = stand.music.now_messages.pop(stand.gid)  # as after a restart
        old.flags = discord.MessageFlags()
        template = next(
            v for v in stand.bot.persistent_views if type(v).__name__ == "NowPlayingView"
        )
        item = find_item(template, CID_SKIP)
        interaction = FakeInteraction(
            user=listener(stand), guild=stand.guild, channel=stand.home, message=old
        )
        await drive(template, item, interaction)
        await stand.lavalink.settle()
        assert stand.lavalink.now(stand.gid) == "b"
        assert old.deleted, "the adopted panel must be replaced, not stranded"


# --------------------------------------------------------------------------- #
#  The channel stays tidy
# --------------------------------------------------------------------------- #
class TestTidyChannel:
    async def test_button_presses_post_no_messages(self, stand) -> None:
        await stand.play("a", "b", "c")
        sent = len(stand.home.sent)
        for key in (CID_PLAY_PAUSE, CID_PLAY_PAUSE, CID_LOOP, CID_VOLUME_UP, CID_SHUFFLE):
            await press(stand, key)
        assert len(stand.home.sent) == sent

    async def test_a_failure_notice_removes_itself(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad")
        notices = [
            call
            for call in stand.home.send.call_args_list
            if "не удалось" in view_text(call.kwargs.get("view"))
            if call.kwargs.get("view")
        ]
        assert notices and notices[0].kwargs.get("delete_after")

    async def test_a_dead_last_track_leaves_an_idle_panel(self, stand) -> None:
        stand.lavalink.fail("bad", times=100)
        await stand.play("bad")
        assert "Не удалось воспроизвести" in (idle_text(stand.panels()[0]) or "")


def test_every_control_has_a_fixed_id() -> None:
    """A panel posted before a restart keeps working only with fixed ids."""
    from ui.controls import NowPlayingView

    view = NowPlayingView(MagicMock())
    ids = [i.custom_id for i in view.walk_children() if isinstance(i, (ui.Button, ui.Select))]
    assert sorted(ids) == sorted(
        [
            CID_BACK,
            CID_PLAY_PAUSE,
            CID_SKIP,
            CID_STOP,
            CID_SHUFFLE,
            CID_LOOP,
            CID_VOLUME_DOWN,
            CID_VOLUME_UP,
            CID_QUEUE,
            CID_JUMP,
        ]
    )
    assert view.is_persistent()


# --------------------------------------------------------------------------- #
#  Slash commands share the panel's behaviour
# --------------------------------------------------------------------------- #
class TestSlashCommands:
    async def _run(self, stand, command: str, *args: Any, user: Any = None) -> Any:
        interaction = FakeInteraction(
            user=user or listener(stand), guild=stand.guild, channel=stand.home
        )
        callback = getattr(stand.music, command).callback
        await callback(stand.music, interaction, *args)
        await stand.lavalink.settle()
        return interaction.record

    async def test_play_announces_briefly_and_updates_up_next(self, stand) -> None:
        from cogs.music import ADDED_NOTICE_TTL

        await stand.play("now")

        async def resolve(query: str):
            return [stand.lavalink.track(query)]

        stand.music._resolve = resolve  # type: ignore[method-assign]
        record = await self._run(stand, "play", "added later")
        notice = record.followups[0]
        assert "added later" in notice["content"]
        notice["message"].delete.assert_awaited_once_with(delay=ADDED_NOTICE_TTL)
        assert "added later" in panel_text(stand), "Далее must list the new track"

    @pytest.mark.parametrize(
        ("command", "args"),
        [("pause", ()), ("skip", ()), ("shuffle", ()), ("clear", ())],
    )
    async def test_control_replies_are_private(self, stand, command, args) -> None:
        await stand.play("a", "b", "c")
        record = await self._run(stand, command, *args)
        assert record.messages and record.messages[0].get("ephemeral") is True

    async def test_a_command_shows_up_as_the_last_action(self, stand) -> None:
        await stand.play("a")
        await self._run(stand, "pause", user=listener(stand, 8))
        assert "⏸️ Пауза — user8" in panel_text(stand)

    async def test_stop_by_command_names_who_stopped(self, stand) -> None:
        await stand.play("a")
        panel = stand.music.now_messages[stand.gid]
        await self._run(stand, "stop", user=listener(stand, 9))
        assert "остановлено — user9" in (idle_text(panel) or "")
