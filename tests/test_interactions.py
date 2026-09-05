"""Every button and select must acknowledge its interaction.

Discord allows a component callback three seconds to respond exactly once.
A path that returns without responding shows "This interaction failed" and the
button appears to hang; a path that responds twice raises and the user sees an
error instead of the result. Both are invisible to unit tests that call the
logic directly, so these tests dispatch through the real view machinery.

The environment is deliberately hostile - nothing configured, no player, no
permissions - because that is where the unhandled paths hide.
"""

from __future__ import annotations

import discord
import pytest
from discord import ui

from core.bot import MusicBot
from tests.interaction_harness import (
    DoubleResponse,
    FakeInteraction,
    drive,
    interactive_items,
    make_channel,
    make_guild,
    make_member,
    make_role,
)


@pytest.fixture
async def bot(tmp_path, make_settings):
    instance = MusicBot(make_settings(DATABASE_PATH=str(tmp_path / "ix.db")))
    await instance.db.connect()
    try:
        yield instance
    finally:
        await instance.db.close()


@pytest.fixture
async def loaded_bot(bot):
    from core.bot import INITIAL_EXTENSIONS

    for extension in INITIAL_EXTENSIONS:
        await bot.load_extension(extension)
    return bot


def scene(*, can_send: bool = True):
    """A guild, a channel in it and a member who is in the channel."""
    guild = make_guild()
    channel = make_channel(guild=guild, can_send=can_send)
    member = make_member(1, guild=guild, top_role_position=10)
    guild.get_member = lambda _id: member
    return guild, channel, member


def interaction_for(
    guild, channel, member, *, message=None, values=None
) -> FakeInteraction:
    return FakeInteraction(
        user=member, guild=guild, channel=channel, message=message, values=values
    )


# --------------------------------------------------------------------------- #
#  The core invariant, applied to every view in the bot
# --------------------------------------------------------------------------- #
def all_views(bot: MusicBot) -> dict[str, ui.LayoutView]:
    """One instance of every interactive panel, built as production builds it."""
    from ui.builder import GigaBuilderView
    from ui.builder.fields import FieldActionRow, FieldPickerView, ReorderFieldsView
    from ui.builder.images import ImageActionView
    from ui.controls import NowPlayingView
    from ui.tickets import RulesPanel, TicketControls

    _guild, channel, member = scene()
    music = bot.get_cog("Music")
    tickets = bot.get_cog("Tickets")
    help_cog = bot.get_cog("Help")

    builder = GigaBuilderView(member, channel, None, bot)
    builder.state.add_field("поле", "значение", inline=False)
    builder.state.add_field("другое", "значение", inline=False)
    builder.render()

    from cogs.help import HelpPanel

    views: dict[str, ui.LayoutView] = {
        "now_playing": NowPlayingView(music),
        "rules_panel": RulesPanel(tickets),
        "ticket_controls": TicketControls(tickets, number=1, owner=member),
        "help_panel": HelpPanel(help_cog, member),
        "builder": builder,
        "builder_field_picker": FieldPickerView(builder),
        "builder_reorder": ReorderFieldsView(builder),
        "builder_image": ImageActionView(builder, "image"),
    }

    picker = FieldPickerView(builder)
    picker.clear_items()
    picker.add_item(FieldActionRow(0))
    views["builder_field_actions"] = picker
    return views


def view_cases(bot: MusicBot) -> list[tuple[str, ui.LayoutView, ui.Item]]:
    cases = []
    for name, view in all_views(bot).items():
        for item in interactive_items(view):
            label = getattr(item, "label", None) or getattr(item, "placeholder", "select")
            cases.append((f"{name}:{label}", view, item))
    return cases


async def test_every_component_acknowledges_its_interaction(loaded_bot) -> None:
    """The headline check: no button may leave an interaction unanswered."""
    guild, channel, member = scene()
    failures: list[str] = []

    for name, view, item in view_cases(loaded_bot):
        values = (
            [item.options[0].value]
            if isinstance(item, ui.Select) and item.options
            else None
        )
        interaction = interaction_for(
            guild, channel, member, message=MagicMessage(), values=values
        )
        try:
            record = await drive(view, item, interaction)
        except DoubleResponse as error:
            failures.append(f"{name}: {error}")
            continue
        if not record.acknowledged:
            failures.append(f"{name}: returned without acknowledging the interaction")

    assert not failures, "unacknowledged or double-answered components:\n" + "\n".join(
        failures
    )


class MagicMessage:
    """A stand-in for interaction.message on a component interaction."""

    def __init__(self) -> None:
        self.id = 123

    async def edit(self, **kwargs):
        return self

    async def delete(self) -> None:
        return None


# --------------------------------------------------------------------------- #
#  Playback controls
# --------------------------------------------------------------------------- #
class TestPlaybackControls:
    async def _press(self, loaded_bot, label: str, *, member=None):
        from ui.controls import NowPlayingView

        guild, channel, default_member = scene()
        member = member or default_member
        view = NowPlayingView(loaded_bot.get_cog("Music"))
        item = next(
            i for i in interactive_items(view) if getattr(i, "label", "") == label
        )
        interaction = interaction_for(guild, channel, member, message=MagicMessage())
        return await drive(view, item, interaction)

    @pytest.mark.parametrize("label", ["Пауза", "Скип", "Стоп"])
    async def test_answers_when_no_player_is_connected(self, loaded_bot, label) -> None:
        """The common real-world case: the panel outlived the voice session."""
        record = await self._press(loaded_bot, label)
        assert record.acknowledged, f"{label} left the interaction hanging"
        assert record.followups, f"{label} deferred but never told the user anything"

    @pytest.mark.parametrize("label", ["Пауза", "Скип", "Стоп"])
    async def test_non_dj_is_refused_without_hanging(self, loaded_bot, label) -> None:
        guild, channel, member = scene()
        dj_role = make_role(555, name="DJ")
        await loaded_bot.db.update_settings(guild.id, dj_role_id=dj_role.id)
        member.guild_permissions = discord.Permissions.none()
        member.roles = []

        from ui.controls import NowPlayingView

        view = NowPlayingView(loaded_bot.get_cog("Music"))
        item = next(i for i in interactive_items(view) if getattr(i, "label", "") == label)
        record = await drive(view, item, interaction_for(guild, channel, member))
        assert record.acks == ["send_message"], f"{label}: DJ refusal must answer once"

    async def test_pressing_twice_does_not_double_respond(self, loaded_bot) -> None:
        """A double click reuses neither the record nor the response object."""
        for _ in range(2):
            record = await self._press(loaded_bot, "Скип")
            assert record.acknowledged


# --------------------------------------------------------------------------- #
#  Ticket and rules panel
# --------------------------------------------------------------------------- #
class TestRulesPanel:
    def _view(self, loaded_bot):
        from ui.tickets import RulesPanel

        return RulesPanel(loaded_bot.get_cog("Tickets"))

    def _button(self, view, label):
        return next(i for i in interactive_items(view) if getattr(i, "label", "") == label)

    async def test_verify_without_configuration_answers(self, loaded_bot) -> None:
        guild, channel, member = scene()
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Согласен с правилами"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_message"]

    async def test_verify_reports_a_role_above_the_bot(self, loaded_bot) -> None:
        """Discord would refuse the grant; the user must learn why."""
        guild, channel, member = scene()
        high_role = make_role(777, position=99, name="Verified")
        guild.get_role = lambda _id: high_role
        await loaded_bot.db.update_ticket_config(guild.id, verify_role_id=high_role.id)

        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Согласен с правилами"),
            interaction_for(guild, channel, member),
        )
        assert record.acknowledged
        member.add_roles.assert_not_awaited()

    async def test_verify_is_idempotent_for_an_already_verified_member(
        self, loaded_bot
    ) -> None:
        guild, channel, member = scene()
        role = make_role(778, position=2, name="Verified")
        guild.get_role = lambda _id: role
        member.roles = [role]
        await loaded_bot.db.update_ticket_config(guild.id, verify_role_id=role.id)

        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Согласен с правилами"),
            interaction_for(guild, channel, member),
        )
        assert record.acknowledged
        member.add_roles.assert_not_awaited()

    async def test_ticket_button_without_configuration_answers(self, loaded_bot) -> None:
        guild, channel, member = scene()
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Связаться с администрацией"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_message"]
        assert not record.modals, "an unconfigured system must not open the form"

    async def test_ticket_button_opens_the_modal_once_configured(self, loaded_bot) -> None:
        guild, channel, member = scene()
        await loaded_bot.db.update_ticket_config(
            guild.id, category_id=1, support_role_id=2
        )
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Связаться с администрацией"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_modal"] and record.modals

    async def test_open_ticket_limit_is_enforced_and_answered(self, loaded_bot) -> None:
        guild, channel, member = scene()
        await loaded_bot.db.update_ticket_config(
            guild.id, category_id=1, support_role_id=2
        )
        from cogs.tickets import MAX_OPEN_TICKETS

        for n in range(MAX_OPEN_TICKETS):
            await loaded_bot.db.create_ticket(
                guild_id=guild.id, channel_id=500 + n, owner_id=member.id,
                category=None, subject=None,
            )
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Связаться с администрацией"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_message"] and not record.modals

    async def test_help_button_answers(self, loaded_bot) -> None:
        guild, channel, member = scene()
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Команды бота"),
            interaction_for(guild, channel, member),
        )
        assert record.acknowledged


class TestTicketControls:
    def _view(self, loaded_bot, **kwargs):
        from ui.tickets import TicketControls

        return TicketControls(loaded_bot.get_cog("Tickets"), number=1, **kwargs)

    def _button(self, view, label):
        return next(i for i in interactive_items(view) if getattr(i, "label", "") == label)

    async def test_claim_outside_a_ticket_channel_answers(self, loaded_bot) -> None:
        """A stale panel in a deleted ticket must not hang."""
        guild, channel, member = scene()
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Взять в работу"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert record.acks == ["send_message"]

    async def test_claim_by_a_non_support_member_answers(self, loaded_bot) -> None:
        guild, channel, member = scene()
        member.guild_permissions = discord.Permissions.none()
        await loaded_bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Взять в работу"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert record.acks == ["send_message"]

    async def test_double_claim_answers_the_second_press(self, loaded_bot) -> None:
        """Two moderators clicking at once: the loser needs a reason, not silence."""
        guild, channel, member = scene()
        await loaded_bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        first = await drive(
            (v1 := self._view(loaded_bot)), self._button(v1, "Взять в работу"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert first.acknowledged

        second = await drive(
            (v2 := self._view(loaded_bot)), self._button(v2, "Взять в работу"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert second.acks == ["send_message"]

    async def test_close_from_the_panel_answers(self, loaded_bot) -> None:
        guild, channel, member = scene()
        await loaded_bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        view = self._view(loaded_bot)
        record = await drive(
            view, self._button(view, "Закрыть тикет"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert record.acknowledged

    async def test_closing_twice_answers_the_second_press(self, loaded_bot) -> None:
        guild, channel, member = scene()
        await loaded_bot.db.create_ticket(
            guild_id=guild.id, channel_id=channel.id, owner_id=5,
            category=None, subject=None,
        )
        for expected_ack in (True, True):
            view = self._view(loaded_bot)
            record = await drive(
                view, self._button(view, "Закрыть тикет"),
                interaction_for(guild, channel, member, message=MagicMessage()),
            )
            assert record.acknowledged is expected_ack


# --------------------------------------------------------------------------- #
#  Builder
# --------------------------------------------------------------------------- #
class TestBuilder:
    def _builder(self, bot):
        from ui.builder import GigaBuilderView

        guild, channel, member = scene()
        view = GigaBuilderView(member, channel, None, bot)
        return view, guild, channel, member

    def _button(self, view, label):
        return next(
            i for i in interactive_items(view) if getattr(i, "label", "") == label
        )

    @pytest.mark.parametrize(
        "label",
        ["Основное", "Автор", "Футер", "Текст над постом", "Добавить поле"],
    )
    async def test_form_buttons_open_a_modal(self, loaded_bot, label) -> None:
        view, guild, channel, member = self._builder(loaded_bot)
        record = await drive(
            view, self._button(view, label), interaction_for(guild, channel, member)
        )
        assert record.acks == ["send_modal"], f"{label} did not open its form"

    @pytest.mark.parametrize("label", ["Изменить/Удалить", "Порядок полей"])
    async def test_field_buttons_answer_with_no_fields(self, loaded_bot, label) -> None:
        """Empty state is the first thing a user hits; it must not hang."""
        view, guild, channel, member = self._builder(loaded_bot)
        record = await drive(
            view, self._button(view, label), interaction_for(guild, channel, member)
        )
        assert record.acks == ["send_message"]

    async def test_separator_button_refuses_past_the_field_limit(self, loaded_bot) -> None:
        view, guild, channel, member = self._builder(loaded_bot)
        from ui.builder.state import MAX_FIELDS

        for i in range(MAX_FIELDS):
            view.state.add_field(f"f{i}", "v", inline=False)
        view.render()
        record = await drive(
            view, self._button(view, "Разделитель"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_message"]

    async def test_publishing_an_oversized_embed_is_refused_not_attempted(
        self, loaded_bot
    ) -> None:
        view, guild, channel, member = self._builder(loaded_bot)
        view.state.embed.description = "x" * 4000
        for i in range(3):
            view.state.add_field(f"f{i}", "y" * 1000, inline=False)
        view.render()
        record = await drive(
            view, self._button(view, "Опубликовать"),
            interaction_for(guild, channel, member),
        )
        assert record.acks == ["send_message"]
        channel.send.assert_not_awaited()

    async def test_publish_answers_when_the_bot_cannot_write(self, loaded_bot) -> None:
        from ui.builder import GigaBuilderView

        guild = make_guild()
        channel = make_channel(guild=guild, can_send=False)
        member = make_member(1, guild=guild, top_role_position=10)
        view = GigaBuilderView(member, channel, None, loaded_bot)
        record = await drive(
            view, self._button(view, "Опубликовать"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert record.acknowledged

    async def test_format_switch_toggles_and_answers(self, loaded_bot) -> None:
        view, guild, channel, member = self._builder(loaded_bot)
        assert view.state.publish_format == "embed"
        record = await drive(
            view, self._button(view, "Формат: эмбед"),
            interaction_for(guild, channel, member),
        )
        assert record.acknowledged
        assert view.state.publish_format == "v2"

    async def test_cancel_answers(self, loaded_bot) -> None:
        view, guild, channel, member = self._builder(loaded_bot)
        record = await drive(
            view, self._button(view, "Отменить"),
            interaction_for(guild, channel, member, message=MagicMessage()),
        )
        assert record.acknowledged

    async def test_someone_elses_builder_is_refused_and_answered(
        self, loaded_bot
    ) -> None:
        """interaction_check must answer, or the stranger's click hangs."""
        view, guild, channel, _owner = self._builder(loaded_bot)
        stranger = make_member(42, guild=guild)
        record = await drive(
            view, self._button(view, "Основное"),
            interaction_for(guild, channel, stranger),
        )
        assert record.acks == ["send_message"]

    async def test_deleting_a_field_that_vanished_answers(self, loaded_bot) -> None:
        """The picker was opened, then the field was removed elsewhere."""
        from ui.builder.fields import FieldActionRow, FieldPickerView

        view, guild, channel, member = self._builder(loaded_bot)
        view.state.add_field("поле", "значение", inline=False)
        picker = FieldPickerView(view)
        picker.clear_items()
        row = FieldActionRow(5)  # index that does not exist
        picker.add_item(row)
        item = next(i for i in interactive_items(picker) if getattr(i, "label", "") == "Удалить")
        record = await drive(
            picker, item, interaction_for(guild, channel, member, message=MagicMessage())
        )
        assert record.acknowledged


# --------------------------------------------------------------------------- #
#  Selects
# --------------------------------------------------------------------------- #
class TestSelects:
    async def test_help_menu_switches_pages(self, loaded_bot) -> None:
        from cogs.help import HelpPanel

        guild, channel, member = scene()
        view = HelpPanel(loaded_bot.get_cog("Help"), member)
        select = next(i for i in interactive_items(view) if isinstance(i, ui.Select))
        record = await drive(
            view,
            select,
            interaction_for(
                guild, channel, member, message=MagicMessage(),
                values=[select.options[-1].value],
            ),
        )
        assert record.acks == ["edit_message"]

    async def test_reorder_waits_for_both_halves_then_applies(self, loaded_bot) -> None:
        """Picking only one side must acknowledge without changing anything."""
        from ui.builder import GigaBuilderView
        from ui.builder.fields import ReorderFieldsView

        guild, channel, member = scene()
        builder = GigaBuilderView(member, channel, None, loaded_bot)
        for name in ("A", "B", "C"):
            builder.state.add_field(name, "v", inline=False)
        builder.render()

        view = ReorderFieldsView(builder)
        selects = [i for i in interactive_items(view) if isinstance(i, ui.Select)]
        assert len(selects) == 2

        first = await drive(
            view, selects[0],
            interaction_for(
                guild, channel, member, message=MagicMessage(), values=["0"]
            ),
        )
        assert first.acks == ["defer"], "half-finished choice must still acknowledge"
        assert [f.name for f in builder.state.embed.fields] == ["A", "B", "C"]

        second = await drive(
            view, selects[1],
            interaction_for(
                guild, channel, member, message=MagicMessage(), values=["2"]
            ),
        )
        assert second.acknowledged
        assert [f.name for f in builder.state.embed.fields] == ["B", "A", "C"]

    async def test_colour_preset_applies_and_answers(self, loaded_bot) -> None:
        from ui.builder import GigaBuilderView
        from ui.builder.colors import PRESET_COLORS

        guild, channel, member = scene()
        view = GigaBuilderView(member, channel, None, loaded_bot)
        select = next(
            i for i in interactive_items(view)
            if isinstance(i, ui.Select) and "цвет" in (i.placeholder or "").lower()
        )
        chosen = list(PRESET_COLORS)[1]
        record = await drive(
            view, select,
            interaction_for(
                guild, channel, member, message=MagicMessage(), values=[chosen]
            ),
        )
        assert record.acknowledged
        assert view.state.embed.colour == PRESET_COLORS[chosen]


# --------------------------------------------------------------------------- #
#  Failure handling
# --------------------------------------------------------------------------- #
class TestErrorPaths:
    async def test_a_raising_callback_still_answers(self, loaded_bot) -> None:
        """on_error is the last line of defence against a hung button."""
        from ui.controls import NowPlayingView

        guild, channel, member = scene()
        view = NowPlayingView(loaded_bot.get_cog("Music"))
        item = next(i for i in interactive_items(view) if getattr(i, "label", "") == "Скип")

        async def boom(interaction):
            raise RuntimeError("simulated failure")

        item.callback = boom
        record = await drive(
            view, item, interaction_for(guild, channel, member, message=MagicMessage())
        )
        assert record.acknowledged, "on_error left the interaction hanging"

    async def test_timeout_greys_out_every_nested_button(self, loaded_bot) -> None:
        """A timed-out panel must not keep offering clickable buttons."""
        from ui.builder import GigaBuilderView

        _guild, channel, member = scene()
        view = GigaBuilderView(member, channel, None, loaded_bot)
        view.message = None
        await view.on_timeout()
        assert not [i for i in interactive_items(view) if not i.disabled] or not interactive_items(view)
