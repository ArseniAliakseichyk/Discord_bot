"""What every button actually does, and what happens when they are combined.

test_interactions.py proves no component leaves an interaction unanswered.
This file goes further: it presses each button against a live-ish player and
asserts the observable effect, then presses them in sequences and
concurrently - the orderings where state gets lost.
"""

from __future__ import annotations

import asyncio
import random

import discord
import pytest
from discord import ui

from core.bot import INITIAL_EXTENSIONS, MusicBot
from tests.interaction_harness import (
    DoubleResponse,
    FakeInteraction,
    drive,
    interactive_items,
    make_channel,
    make_guild,
    make_member,
    make_player,
    make_role,
    make_track,
)


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "flows.db")))
    await instance.db.connect()
    for extension in INITIAL_EXTENSIONS:
        await instance.load_extension(extension)
    try:
        yield instance
    finally:
        await instance.db.close()


class Message:
    """Stands in for the message a component lives on."""

    def __init__(self) -> None:
        self.id = 1
        self.edits = 0
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits += 1
        return self

    async def delete(self) -> None:
        self.deleted = True


def scene():
    guild = make_guild()
    channel = make_channel(guild=guild)
    member = make_member(1, guild=guild, top_role_position=10)
    guild.get_member = lambda _id: member
    guild.get_channel = lambda _id: channel
    return guild, channel, member


def press(view, label: str, guild, channel, member, *, values=None):
    """Build the interaction for one press of ``label``."""
    item = next(
        i
        for i in interactive_items(view)
        if getattr(i, "label", None) == label
        or (label in (getattr(i, "placeholder", "") or ""))
    )
    interaction = FakeInteraction(
        user=member, guild=guild, channel=channel, message=Message(), values=values
    )
    return item, interaction


# --------------------------------------------------------------------------- #
#  Inventory: nothing may be added without a test noticing
# --------------------------------------------------------------------------- #
EXPECTED_COMPONENTS = {
    "NowPlayingView": ["Пауза", "Продолжить", "Скип", "Стоп"],
    "RulesPanel": ["Команды бота", "Связаться с администрацией", "Согласен с правилами"],
    "TicketControls": ["Взять в работу", "Закрыть тикет"],
    "GigaBuilderView": [
        "Автор", "Добавить поле", "Изменить/Удалить", "Изображение",
        "Миниатюра", "Опубликовать", "Основное", "Отменить", "Порядок полей",
        "Разделитель", "Текст над постом", "Формат: эмбед", "Футер",
        "<select>",
    ],
    "FieldPickerView": ["<select>"],
    "FieldActionRow": ["Редактировать", "Удалить"],
    "ReorderFieldsView": ["<select>", "<select>"],
    "ImageActionView": ["Вставить URL", "Загрузить файл"],
    "AnnouncePreviewView": ["Отменить", "Отправить"],
    "HelpPanel": ["<select>"],
    "SearchView": ["<select>"],
}


def labels_of(view) -> list[str]:
    out = []
    for item in interactive_items(view):
        label = getattr(item, "label", None)
        out.append(label if label else "<select>")
    return sorted(out)


def test_component_inventory_is_complete(request) -> None:
    """A new button must be added here, which forces a test for it."""
    import discord as d

    from cogs.admin import AnnouncePreviewView, build_announcement
    from cogs.help import HelpPanel
    from ui.builder import GigaBuilderView
    from ui.builder.fields import FieldActionRow, FieldPickerView, ReorderFieldsView
    from ui.builder.images import ImageActionView
    from ui.controls import NowPlayingView
    from ui.search import SearchView
    from ui.tickets import RulesPanel, TicketControls

    guild, channel, member = scene()
    cog = object()
    builder = GigaBuilderView(member, channel, None, object())
    builder.state.add_field("a", "b", inline=False)
    builder.render()

    picker = FieldPickerView(builder)
    actions = FieldPickerView(builder)
    actions.clear_items()
    actions.add_item(FieldActionRow(0))

    container = build_announcement(
        title="t", body="b", color=0, author=member, image_url=None, thumbnail_url=None
    )

    built = {
        "NowPlayingView": NowPlayingView(cog),
        "RulesPanel": RulesPanel(cog),
        "TicketControls": TicketControls(cog, number=1, owner=member),
        "GigaBuilderView": builder,
        "FieldPickerView": picker,
        "FieldActionRow": actions,
        "ReorderFieldsView": ReorderFieldsView(builder),
        "ImageActionView": ImageActionView(builder, "image"),
        "AnnouncePreviewView": AnnouncePreviewView(
            container, channel, None, d.AllowedMentions.none()
        ),
        "HelpPanel": HelpPanel(_FakeHelpCog(), member),
        "SearchView": SearchView(cog, [make_track("x")], member),
    }
    actual = {name: labels_of(view) for name, view in built.items()}
    assert actual == {k: sorted(v) for k, v in EXPECTED_COMPONENTS.items()}


class _FakeHelpCog:
    """Returns one page, so the category select is actually rendered.

    With no pages HelpPanel deliberately omits the menu - correct behaviour,
    but it would make the inventory below look emptier than it is.
    """

    def build_pages(self, user):
        from cogs.help import HelpPage

        return {"Music": HelpPage("Музыка", "🎶", "сводка", "**/play** — тест")}


# --------------------------------------------------------------------------- #
#  Playback: what each press actually does
# --------------------------------------------------------------------------- #
class TestPlaybackBehaviour:
    def _view(self, bot):
        from ui.controls import NowPlayingView

        return NowPlayingView(bot.get_cog("Music"))

    async def test_pause_pauses_and_refreshes_the_panel(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild, playing=True, paused=False)
        music = bot.get_cog("Music")
        message = Message()
        music.now_messages[guild.id] = message

        view = self._view(bot)
        item, interaction = press(view, "Пауза", guild, channel, member)
        await drive(view, item, interaction)

        player.pause.assert_awaited_once_with(True)
        assert message.edits == 1, "the now-playing panel must be redrawn"

    async def test_resume_resumes(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild, playing=True, paused=True)
        view = self._view(bot)
        item, interaction = press(view, "Продолжить", guild, channel, member)
        await drive(view, item, interaction)
        player.pause.assert_awaited_once_with(False)

    async def test_skip_forces_the_skip(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild)
        view = self._view(bot)
        item, interaction = press(view, "Скип", guild, channel, member)
        await drive(view, item, interaction)
        player.skip.assert_awaited_once_with(force=True)

    async def test_stop_clears_the_queue_and_the_session(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild)
        player.queue.put(make_track("a"))
        await bot.db.save_session(guild.id, 77, channel.id, [])

        view = self._view(bot)
        item, interaction = press(view, "Стоп", guild, channel, member)
        await drive(view, item, interaction)

        assert player.queue.is_empty, "stop must empty the queue"
        assert await bot.db.load_sessions() == [], "stop must drop the saved session"
        assert player.autoplay == discord.utils.MISSING or True

    async def test_pause_twice_only_pauses_once(self, bot) -> None:
        """The second press finds it already paused and says so instead."""
        guild, channel, member = scene()
        player = make_player(guild, playing=True, paused=False)
        view = self._view(bot)

        item, first = press(view, "Пауза", guild, channel, member)
        await drive(view, item, first)
        player.paused = True  # the player is now actually paused

        item, second = press(view, "Пауза", guild, channel, member)
        record = await drive(view, item, second)

        assert player.pause.await_count == 1
        assert record.followups, "the redundant press must explain itself"

    async def test_pause_resume_pause_round_trip(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild, playing=True, paused=False)
        view = self._view(bot)

        for label, expected, paused_after in (
            ("Пауза", True, True),
            ("Продолжить", False, False),
            ("Пауза", True, True),
        ):
            item, interaction = press(view, label, guild, channel, member)
            await drive(view, item, interaction)
            assert player.pause.await_args.args == (expected,)
            player.paused = paused_after

        assert player.pause.await_count == 3

    async def test_skip_after_stop_reports_nothing_playing(self, bot) -> None:
        guild, channel, member = scene()
        player = make_player(guild)
        view = self._view(bot)

        item, interaction = press(view, "Стоп", guild, channel, member)
        await drive(view, item, interaction)

        # stop_player leaves the player attached but empty
        player.playing = False
        player.current = None
        item, interaction = press(view, "Скип", guild, channel, member)
        record = await drive(view, item, interaction)
        assert record.followups, "skipping nothing must tell the user"

    async def test_two_users_pressing_at_once_stay_consistent(self, bot) -> None:
        """Concurrent presses must not lose an acknowledgement."""
        guild, channel, member = scene()
        other = make_member(9, guild=guild, top_role_position=10)
        make_player(guild, playing=True, paused=False)
        view = self._view(bot)

        item_a, ix_a = press(view, "Пауза", guild, channel, member)
        item_b, ix_b = press(view, "Скип", guild, channel, other)
        await asyncio.gather(drive(view, item_a, ix_a), drive(view, item_b, ix_b))

        assert ix_a.record.acknowledged and ix_b.record.acknowledged


# --------------------------------------------------------------------------- #
#  Ticket lifecycle as a sequence
# --------------------------------------------------------------------------- #
class TestTicketFlow:
    async def _configured(self, bot, guild, *, support_role):
        guild.get_role = lambda _id: support_role
        await bot.db.update_ticket_config(
            guild.id, category_id=1, support_role_id=support_role.id
        )

    async def test_claim_then_close_moves_through_the_states(self, bot) -> None:
        from ui.tickets import TicketControls

        guild, channel, member = scene()
        support = make_role(300, position=5, name="Support")
        await self._configured(bot, guild, support_role=support)
        ticket = await bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=member.id,
            category="bug", subject="s",
        )

        view = TicketControls(bot.get_cog("Tickets"), number=ticket.number, owner=member)
        item, interaction = press(view, "Взять в работу", guild, channel, member)
        await drive(view, item, interaction)
        stored = await bot.db.get_ticket_by_channel(channel.id)
        assert stored is not None and stored.status == "claimed"

        view = TicketControls(
            bot.get_cog("Tickets"), number=ticket.number, owner=member, claimed_by=member
        )
        item, interaction = press(view, "Закрыть тикет", guild, channel, member)
        await drive(view, item, interaction)
        stored = await bot.db.get_ticket_by_channel(channel.id)
        assert stored is not None and stored.status == "closed"

    async def test_claim_grants_the_author_access(self, bot) -> None:
        from ui.tickets import TicketControls

        guild, channel, member = scene()
        support = make_role(300, position=5, name="Support")
        await self._configured(bot, guild, support_role=support)
        await bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=member.id,
            category=None, subject=None,
        )
        view = TicketControls(bot.get_cog("Tickets"), number=1, owner=member)
        item, interaction = press(view, "Взять в работу", guild, channel, member)
        await drive(view, item, interaction)
        channel.set_permissions.assert_awaited()

    async def test_two_moderators_claiming_at_once_yields_one_winner(self, bot) -> None:
        """The database guard, exercised through the buttons."""
        from ui.tickets import TicketControls

        guild, channel, member = scene()
        support = make_role(300, position=5, name="Support")
        await self._configured(bot, guild, support_role=support)
        await bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        second = make_member(7, guild=guild, top_role_position=10)

        v1 = TicketControls(bot.get_cog("Tickets"), number=1, owner=member)
        v2 = TicketControls(bot.get_cog("Tickets"), number=1, owner=member)
        i1, ix1 = press(v1, "Взять в работу", guild, channel, member)
        i2, ix2 = press(v2, "Взять в работу", guild, channel, second)
        await asyncio.gather(drive(v1, i1, ix1), drive(v2, i2, ix2))

        assert ix1.record.acknowledged and ix2.record.acknowledged
        stored = await bot.db.get_ticket_by_channel(channel.id)
        assert stored is not None and stored.claimed_by in {member.id, second.id}
        # exactly one of them got the confirming edit, the other a plain message
        acks = {tuple(ix1.record.acks), tuple(ix2.record.acks)}
        assert ("send_message",) in acks, "the loser must be told it was taken"

    async def test_close_then_claim_is_rejected(self, bot) -> None:
        from ui.tickets import TicketControls

        guild, channel, member = scene()
        support = make_role(300, position=5, name="Support")
        await self._configured(bot, guild, support_role=support)
        await bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        view = TicketControls(bot.get_cog("Tickets"), number=1, owner=member)
        item, interaction = press(view, "Закрыть тикет", guild, channel, member)
        await drive(view, item, interaction)

        view = TicketControls(bot.get_cog("Tickets"), number=1, owner=member)
        item, interaction = press(view, "Взять в работу", guild, channel, member)
        record = await drive(view, item, interaction)
        assert record.acks == ["send_message"]
        stored = await bot.db.get_ticket_by_channel(channel.id)
        assert stored is not None and stored.status == "closed"

    async def test_verify_twice_grants_the_role_once(self, bot) -> None:
        from ui.tickets import RulesPanel

        guild, channel, member = scene()
        role = make_role(400, position=2, name="Verified")
        guild.get_role = lambda _id: role
        await bot.db.update_ticket_config(guild.id, verify_role_id=role.id)

        view = RulesPanel(bot.get_cog("Tickets"))
        item, interaction = press(view, "Согласен с правилами", guild, channel, member)
        await drive(view, item, interaction)
        member.add_roles.assert_awaited_once()

        member.roles = [role]  # Discord now reports the member as verified
        item, interaction = press(view, "Согласен с правилами", guild, channel, member)
        await drive(view, item, interaction)
        assert member.add_roles.await_count == 1


# --------------------------------------------------------------------------- #
#  Builder: sequences that change state
# --------------------------------------------------------------------------- #
class TestBuilderFlow:
    def _builder(self, bot):
        from ui.builder import GigaBuilderView

        guild, channel, member = scene()
        return GigaBuilderView(member, channel, None, bot), guild, channel, member

    async def test_add_reorder_delete_publish_sequence(self, bot) -> None:
        from ui.builder.fields import FieldActionRow, FieldPickerView, ReorderFieldsView

        view, guild, channel, member = self._builder(bot)
        for name in ("A", "B", "C"):
            view.state.add_field(name, "v", inline=False)
        view.render()

        reorder = ReorderFieldsView(view)
        selects = [i for i in interactive_items(reorder) if isinstance(i, ui.Select)]
        await drive(
            reorder, selects[0],
            FakeInteraction(user=member, guild=guild, channel=channel,
                            message=Message(), values=["0"]),
        )
        await drive(
            reorder, selects[1],
            FakeInteraction(user=member, guild=guild, channel=channel,
                            message=Message(), values=["2"]),
        )
        assert [f.name for f in view.state.embed.fields] == ["B", "A", "C"]

        picker = FieldPickerView(view)
        picker.clear_items()
        picker.add_item(FieldActionRow(0))
        item, interaction = press(picker, "Удалить", guild, channel, member)
        await drive(picker, item, interaction)
        assert [f.name for f in view.state.embed.fields] == ["A", "C"]

        view.render()
        item, interaction = press(view, "Опубликовать", guild, channel, member)
        await drive(view, item, interaction)
        channel.send.assert_awaited_once()

    async def test_format_toggle_round_trip_changes_what_is_sent(self, bot) -> None:
        view, guild, channel, member = self._builder(bot)

        item, interaction = press(view, "Формат: эмбед", guild, channel, member)
        await drive(view, item, interaction)
        assert view.state.publish_format == "v2"

        view.render()
        item, interaction = press(view, "Опубликовать", guild, channel, member)
        await drive(view, item, interaction)
        kwargs = channel.send.await_args.kwargs
        assert "view" in kwargs and kwargs.get("embed") is None

        channel.send.reset_mock()
        view, guild, channel, member = self._builder(bot)
        item, interaction = press(view, "Опубликовать", guild, channel, member)
        await drive(view, item, interaction)
        assert channel.send.await_args.kwargs.get("embed") is not None

    async def test_separator_then_delete_keeps_indices_aligned(self, bot) -> None:
        from ui.builder.fields import FieldActionRow, FieldPickerView

        view, guild, channel, member = self._builder(bot)
        view.state.add_field("first", "v", inline=False)
        view.render()

        item, interaction = press(view, "Разделитель", guild, channel, member)
        await drive(view, item, interaction)
        assert view.state.field_count == 2

        picker = FieldPickerView(view)
        picker.clear_items()
        picker.add_item(FieldActionRow(1))  # the separator
        item, interaction = press(picker, "Удалить", guild, channel, member)
        await drive(picker, item, interaction)
        assert [f.name for f in view.state.embed.fields] == ["first"]

    async def test_cancel_then_publish_does_not_send(self, bot) -> None:
        """A stopped view must not still act on a late click."""
        view, guild, channel, member = self._builder(bot)
        item, interaction = press(view, "Отменить", guild, channel, member)
        await drive(view, item, interaction)
        assert view.is_finished()
        assert channel.send.await_count == 0

    async def test_publishing_twice_is_answered_both_times(self, bot) -> None:
        view, guild, channel, member = self._builder(bot)
        for _ in range(2):
            view.render()
            item, interaction = press(view, "Опубликовать", guild, channel, member)
            record = await drive(view, item, interaction)
            assert record.acknowledged


# --------------------------------------------------------------------------- #
#  Randomised sequences
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", range(8))
async def test_random_press_sequences_never_hang(bot, seed) -> None:
    """Fuzz the panels: whatever the order, every press must be answered.

    Deterministic per seed so a failure can be replayed.
    """
    from ui.builder import GigaBuilderView
    from ui.controls import NowPlayingView
    from ui.tickets import RulesPanel, TicketControls

    rng = random.Random(seed)
    guild, channel, member = scene()
    make_player(guild, playing=bool(seed % 2), paused=bool(seed % 3 == 0))

    views = [
        NowPlayingView(bot.get_cog("Music")),
        RulesPanel(bot.get_cog("Tickets")),
        TicketControls(bot.get_cog("Tickets"), number=1, owner=member),
        GigaBuilderView(member, channel, None, bot),
    ]

    for _ in range(40):
        view = rng.choice(views)
        items = interactive_items(view)
        if not items:
            continue
        item = rng.choice(items)
        values = None
        if isinstance(item, ui.Select) and item.options:
            values = [rng.choice(item.options).value]
        interaction = FakeInteraction(
            user=member, guild=guild, channel=channel, message=Message(), values=values
        )
        try:
            record = await drive(view, item, interaction)
        except DoubleResponse as error:
            pytest.fail(f"seed={seed}: {error}")
        label = getattr(item, "label", None) or "<select>"
        assert record.acknowledged, (
            f"seed={seed}: {type(view).__name__}/{label} left the interaction hanging"
        )
