"""Components V2 helpers and the limits every panel has to respect.

Discord rejects a LayoutView holding more than 40 components or more than 4000
characters of display text, and the failure surfaces only when the message is
actually sent — so the budgets are checked here instead.
"""

from __future__ import annotations

import discord
import pytest
from discord import ui

from core.constants import MAX_V2_COMPONENTS, V2_TEXT_LIMIT
from ui.v2 import (
    PanelView,
    count_components,
    disable_all_v2,
    embed_to_container,
    fits,
    make_panel,
    split_text,
    text_length,
)


class TestSplitText:
    def test_short_text_is_one_chunk(self) -> None:
        assert split_text("привет", 100) == ["привет"]

    def test_chunks_respect_the_limit(self) -> None:
        chunks = split_text("строка\n" * 2000, 500)
        assert all(len(chunk) <= 500 for chunk in chunks)

    def test_never_yields_an_empty_chunk(self) -> None:
        """An empty TextDisplay is rejected by Discord."""
        chunks = split_text("a\n\n\n\nb", 10)
        assert all(chunk.strip() for chunk in chunks)

    def test_a_single_overlong_line_is_hard_split(self) -> None:
        chunks = split_text("x" * 250, 100)
        assert len(chunks) == 3
        assert all(len(chunk) <= 100 for chunk in chunks)

    def test_rejects_a_non_positive_limit(self) -> None:
        with pytest.raises(ValueError):
            split_text("x", 0)


class TestMakePanel:
    def test_title_and_body(self) -> None:
        container = make_panel(title="Заголовок", body="Текст")
        rendered = container.to_component_dict()
        assert rendered["type"] == discord.ComponentType.container.value

    def test_a_long_body_is_split_rather_than_overflowing(self) -> None:
        view = PanelView(timeout=None)
        view.add_item(make_panel(title="T", body="строка\n" * 3000))
        assert text_length(view) <= V2_TEXT_LIMIT

    def test_thumbnail_becomes_a_section_accessory(self) -> None:
        container = make_panel(title="T", body="b", thumbnail="https://e/x.png")
        first = container.children[0]
        assert isinstance(first, ui.Section)
        assert isinstance(first.accessory, ui.Thumbnail)


class TestDisableAll:
    def test_reaches_buttons_nested_in_containers(self) -> None:
        """view.children would miss them — v2 buttons live inside containers."""

        class Row(ui.ActionRow):
            @ui.button(label="x", custom_id="x")
            async def press(self, interaction, button) -> None: ...

        view = PanelView(timeout=None)
        container = make_panel(body="b")
        container.add_item(Row())
        view.add_item(container)

        buttons = [i for i in view.walk_children() if isinstance(i, ui.Button)]
        assert buttons and not buttons[0].disabled
        disable_all_v2(view)
        assert all(button.disabled for button in buttons)


class TestEmbedToContainer:
    def test_all_fields_collapse_into_one_text_display(self) -> None:
        """25 separate components would blow the 40-component budget."""
        embed = discord.Embed(title="T", description="D")
        for i in range(25):
            embed.add_field(name=f"F{i}", value="v", inline=False)
        container = embed_to_container(embed)
        texts = [c for c in container.children if isinstance(c, ui.TextDisplay)]
        # header + description + one combined fields block
        assert len(texts) == 3

    def test_stays_within_limits_at_maximum_size(self) -> None:
        embed = discord.Embed(title="T" * 200, description="D" * 3000)
        for i in range(25):
            embed.add_field(name=f"F{i}" * 10, value="v" * 100, inline=False)
        embed.set_footer(text="footer")
        embed.set_image(url="https://e/i.png")
        view = PanelView(timeout=None)
        view.add_item(embed_to_container(embed))
        assert count_components(view) <= MAX_V2_COMPONENTS
        assert text_length(view) <= V2_TEXT_LIMIT
        assert fits(view)

    def test_empty_embed_produces_a_valid_container(self) -> None:
        container = embed_to_container(discord.Embed())
        assert container.to_component_dict()["type"] == discord.ComponentType.container.value

    def test_colour_carries_over_as_the_accent(self) -> None:
        embed = discord.Embed(title="T", colour=discord.Colour(0x123456))
        rendered = embed_to_container(embed).to_component_dict()
        assert rendered["accent_color"] == 0x123456


class TestPanelBudgets:
    def test_the_builder_panel_fits_when_full(self, make_settings) -> None:
        """The busiest panel in the bot: full embed plus every control row."""
        from core.bot import MusicBot
        from ui.builder import GigaBuilderView

        class Channel:
            id = 1
            mention = "#c"

            def permissions_for(self, _):
                return discord.Permissions(send_messages=True)

        class User:
            id = 7
            display_name = "u"

        bot = MusicBot(make_settings())
        view = GigaBuilderView(User(), Channel(), None, bot)
        for i in range(25):
            view.state.add_field(f"Поле {i}", "значение", inline=False)
        view.render()
        assert count_components(view) <= MAX_V2_COMPONENTS
        assert text_length(view) <= V2_TEXT_LIMIT
