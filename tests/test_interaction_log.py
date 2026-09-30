"""The one-line-per-interaction log used to reconstruct live problems."""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from cogs.events import describe_interaction


def interaction(kind: discord.InteractionType, data: dict) -> discord.Interaction:
    return SimpleNamespace(type=kind, data=data)  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("kind", "data", "expected"),
    [
        (
            discord.InteractionType.application_command,
            {"name": "play", "options": [{"name": "query", "value": "АлСми"}]},
            "/play query='АлСми'",
        ),
        (
            discord.InteractionType.application_command,
            {
                "name": "ticket",
                "options": [
                    {
                        "name": "config",
                        "options": [{"name": "role", "options": [{"name": "role", "value": "5"}]}],
                    }
                ],
            },
            "/ticket config role role='5'",
        ),
        (discord.InteractionType.application_command, {"name": "skip"}, "/skip"),
        (discord.InteractionType.component, {"custom_id": "np:skip"}, "component np:skip"),
        (
            discord.InteractionType.component,
            {"custom_id": "search:pick", "values": ["2"]},
            "component search:pick ['2']",
        ),
        (discord.InteractionType.modal_submit, {"custom_id": "ticket:modal"}, "modal ticket:modal"),
    ],
)
def test_describe(kind, data, expected) -> None:
    assert describe_interaction(interaction(kind, data)) == expected


def test_long_values_are_cut() -> None:
    text = describe_interaction(
        interaction(
            discord.InteractionType.application_command,
            {"name": "play", "options": [{"name": "query", "value": "x" * 500}]},
        )
    )
    assert len(text) < 120


def test_missing_data_does_not_raise() -> None:
    assert (
        describe_interaction(interaction(discord.InteractionType.component, None)) == "component ?"
    )  # type: ignore[arg-type]
