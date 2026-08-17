"""BuilderState rules, including regressions for the bugs found in the audit."""

from __future__ import annotations

import discord
import pytest

from ui.builder.colors import expand_color_tags, parse_hex_color
from ui.builder.state import MAX_FIELDS, MAX_TOTAL, BuilderError, BuilderState


def state_with(*names: str) -> BuilderState:
    state = BuilderState()
    for name in names:
        state.add_field(name, f"value-{name}", inline=False)
    return state


def names(state: BuilderState) -> list[str]:
    return [f.name for f in state.embed.fields]


class TestMoveField:
    """Regression: moving a field forward landed it one position too late.

    ``insert(before, pop(source))`` shifts every later item left when the popped
    item came first, so the field ended up *after* the target instead of before.
    """

    def test_move_forward_lands_before_the_target(self) -> None:
        state = state_with("A", "B", "C")
        state.move_field(0, 2)  # move A before C
        assert names(state) == ["B", "A", "C"]

    def test_move_backward_lands_before_the_target(self) -> None:
        state = state_with("A", "B", "C")
        state.move_field(2, 0)  # move C before A
        assert names(state) == ["C", "A", "B"]

    def test_move_to_the_last_position(self) -> None:
        state = state_with("A", "B", "C", "D")
        state.move_field(1, 3)
        assert names(state) == ["A", "C", "B", "D"]

    def test_moving_onto_itself_is_rejected(self) -> None:
        state = state_with("A", "B")
        with pytest.raises(BuilderError):
            state.move_field(1, 1)

    def test_out_of_range_is_rejected(self) -> None:
        state = state_with("A", "B")
        with pytest.raises(BuilderError):
            state.move_field(0, 5)

    def test_inline_flags_survive_the_rebuild(self) -> None:
        state = BuilderState()
        state.add_field("A", "a", inline=True)
        state.add_field("B", "b", inline=False)
        state.add_field("C", "c", inline=True)
        state.move_field(2, 0)
        assert [f.inline for f in state.embed.fields] == [True, True, False]


class TestFieldBounds:
    def test_editing_a_removed_field_is_rejected(self) -> None:
        """Regression: a stale index used to raise IndexError from discord.py."""
        state = state_with("A", "B")
        state.remove_field(1)
        with pytest.raises(BuilderError):
            state.set_field(1, "X", "x", inline=False)

    def test_removing_out_of_range_is_rejected(self) -> None:
        with pytest.raises(BuilderError):
            state_with("A").remove_field(3)

    def test_field_limit_is_enforced(self) -> None:
        state = BuilderState()
        for i in range(MAX_FIELDS):
            state.add_field(f"F{i}", "v", inline=False)
        with pytest.raises(BuilderError):
            state.add_field("overflow", "v", inline=False)
        with pytest.raises(BuilderError):
            state.add_separator()


class TestMainSettings:
    def test_clearing_the_colour_actually_clears_it(self) -> None:
        """Regression: an emptied colour field left the previous colour set."""
        state = BuilderState()
        state.embed.colour = discord.Color.red()
        state.apply_main(
            title="t",
            url=None,
            description="d",
            color=None,
            clear_color=True,
            timestamp=False,
        )
        assert state.embed.colour is None

    def test_colour_is_kept_when_not_being_changed(self) -> None:
        state = BuilderState()
        state.embed.colour = discord.Color.red()
        state.apply_main(
            title="t",
            url=None,
            description="d",
            color=discord.Color.green(),
            clear_color=False,
            timestamp=False,
        )
        assert state.embed.colour == discord.Color.green()

    def test_timestamp_toggles(self) -> None:
        state = BuilderState()
        state.apply_main(
            title="t", url=None, description=None, color=None,
            clear_color=False, timestamp=True,
        )
        assert state.embed.timestamp is not None
        state.apply_main(
            title="t", url=None, description=None, color=None,
            clear_color=False, timestamp=False,
        )
        assert state.embed.timestamp is None


class TestValidation:
    def test_oversized_embed_is_reported_before_sending(self) -> None:
        """Regression: publishing used to fail with a bare HTTP 400."""
        state = BuilderState()
        state.embed.description = "x" * 4000
        for i in range(3):
            state.add_field(f"F{i}", "y" * 1000, inline=False)
        assert state.total_length() > MAX_TOTAL
        problem = state.validate()
        assert problem is not None and "слишком длинный" in problem

    def test_empty_embed_is_reported(self) -> None:
        state = BuilderState()
        state.embed.title = None
        state.embed.description = None
        assert state.validate() is not None

    def test_normal_embed_passes(self) -> None:
        assert BuilderState().validate() is None


class TestColors:
    def test_ansi_output_contains_the_escape_byte(self) -> None:
        """Regression: without ESC, Discord printed a literal "[0;31m"."""
        out = expand_color_tags("{color:red}Внимание{/color}")
        assert "\x1b[0;31m" in out
        assert out.startswith("```ansi\n")
        assert out.endswith("\n```")

    def test_unknown_colour_falls_back_instead_of_failing(self) -> None:
        out = expand_color_tags("{color:chartreuse}hi{/color}")
        assert "\x1b[0;0m" in out

    def test_text_without_tags_is_unchanged(self) -> None:
        assert expand_color_tags("обычный текст") == "обычный текст"

    def test_multiple_spans(self) -> None:
        out = expand_color_tags("{color:red}a{/color} и {color:blue}b{/color}")
        assert out.count("```ansi") == 2

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("#f00", 0xFF0000),  # short form must expand, not parse as 0x000F00
            ("#FF0000", 0xFF0000),
            ("ff0000", 0xFF0000),
            ("#0f0", 0x00FF00),
        ],
    )
    def test_hex_parsing(self, value: str, expected: int) -> None:
        colour = parse_hex_color(value)
        assert colour is not None and colour.value == expected

    @pytest.mark.parametrize("value", ["", "#ggg", "#12345", "red", "#"])
    def test_invalid_hex_is_rejected(self, value: str) -> None:
        assert parse_hex_color(value) is None


class TestFinalEmbed:
    def test_final_embed_does_not_mutate_the_working_copy(self) -> None:
        state = BuilderState()
        state.embed.description = "{color:red}x{/color}"
        final = state.final_embed()
        assert "\x1b" in (final.description or "")
        assert state.embed.description == "{color:red}x{/color}"

    def test_field_values_are_expanded_too(self) -> None:
        state = BuilderState()
        state.add_field("F", "{color:green}ok{/color}", inline=False)
        final = state.final_embed()
        assert "\x1b[0;32m" in final.fields[0].value
