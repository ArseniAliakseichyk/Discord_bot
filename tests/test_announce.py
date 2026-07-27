"""Hex colour parsing for /announce."""

from __future__ import annotations

import pytest

from cogs.admin import parse_hex_color


class TestParseHexColor:
    def test_six_digit_form(self) -> None:
        assert parse_hex_color("#5865F2") == 0x5865F2

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("#f00", 0xFF0000), ("#0f0", 0x00FF00), ("#00f", 0x0000FF), ("#fff", 0xFFFFFF)],
    )
    def test_three_digit_form_is_expanded(self, value: str, expected: int) -> None:
        # Regression: int("f00", 16) is 0x000F00 (dark green), not red.
        assert parse_hex_color(value) == expected

    def test_case_insensitive(self) -> None:
        assert parse_hex_color("#ABCDEF") == parse_hex_color("#abcdef")

    @pytest.mark.parametrize("value", ["", "5865F2", "#12", "#12345", "#gggggg", "red"])
    def test_invalid_input_returns_none(self, value: str) -> None:
        assert parse_hex_color(value) is None
