"""/ticket panel: the server's rules as it wrote them, laid out like before.

The rewrite had cut the rules to a generic summary and put the server icon
under the text as a large image. The text and the small icon beside the
welcome are what members saw before, and what the owner asked to keep.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from discord import ui

from core.constants import MAX_V2_COMPONENTS, V2_TEXT_LIMIT
from ui.tickets import (
    CID_HELP,
    CID_OPEN_TICKET,
    CID_VERIFY,
    DEFAULT_RULES,
    RULES_FOOTER,
    RulesPanel,
)
from ui.v2 import count_components, text_length

ICON = "https://cdn.discordapp.com/icons/1/abc.png"


def texts(view: ui.LayoutView) -> str:
    return "\n".join(i.content for i in view.walk_children() if isinstance(i, ui.TextDisplay))


def container_of(view: ui.LayoutView) -> Any:
    (container,) = view.children
    return container


class TestText:
    def test_every_section_of_the_original_rules_is_there(self) -> None:
        text = texts(RulesPanel(MagicMock()))
        for line in (
            "# 🦩 Welcome to Гача 🦩",
            "## 🏛️ Наши Три Столпа",
            "И даже черный 🥰",
            "Я не шучу. Реально сразу в бан 😇.",
            "## 🗣️ Голос vs. ⌨️ Текст",
            "Трэш-ток, шутки, «performance»",
            "Все команды ботов – в `канале - 🎧bot`.",
            "## 👑 Иерархия Гачи",
            "`🤍Император🤍`, `⚔️Лорды🛡️`",
            "кастомную роль",
            "## 🎙️ Твой Сетап",
            "перфоратор или эхо из 2005-го",
            "`HyperX Cloud` или `SteelSeries Arctis`",
            "и погнали!",
        ):
            assert line in text, f"missing from the rules: {line}"

    def test_a_guilds_own_text_replaces_the_default_without_the_footer(self) -> None:
        text = texts(RulesPanel(MagicMock(), rules_text="# Наши правила\n\nНе ругаться."))
        assert "Наши правила" in text
        assert "Welcome to Гача" not in text
        assert RULES_FOOTER not in text


class TestLayout:
    def test_the_icon_sits_beside_the_welcome_as_before(self) -> None:
        container = container_of(RulesPanel(MagicMock(), icon_url=ICON))
        first = container.children[0]
        assert isinstance(first, ui.Section)
        assert isinstance(first.accessory, ui.Thumbnail)
        assert first.accessory.media.url == ICON
        assert "Welcome to Гача" in first.children[0].content
        assert "Иерархия" not in first.children[0].content, "only the welcome goes beside it"

    def test_no_large_image_under_the_text(self) -> None:
        view = RulesPanel(MagicMock(), icon_url=ICON)
        assert not any(isinstance(i, ui.MediaGallery) for i in view.walk_children())

    def test_without_an_icon_the_welcome_is_plain_text(self) -> None:
        first = container_of(RulesPanel(MagicMock())).children[0]
        assert isinstance(first, ui.TextDisplay)

    def test_the_buttons_come_last(self) -> None:
        container = container_of(RulesPanel(MagicMock(), icon_url=ICON))
        row = container.children[-1]
        assert isinstance(row, ui.ActionRow)
        assert [b.custom_id for b in row.children] == [CID_VERIFY, CID_OPEN_TICKET, CID_HELP]

    def test_fits_discords_limits_even_with_the_longest_custom_text(self) -> None:
        for rules in (None, DEFAULT_RULES, "## Раздел\n" + "ж" * 3980):
            view = RulesPanel(MagicMock(), rules_text=rules, icon_url=ICON)
            assert text_length(view) <= V2_TEXT_LIMIT
            assert count_components(view) <= MAX_V2_COMPONENTS
