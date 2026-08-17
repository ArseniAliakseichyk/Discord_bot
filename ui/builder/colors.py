"""Colour presets and the ``{color:…}`` markup used by the builder."""

from __future__ import annotations

import re

import discord

PRESET_COLORS: dict[str, discord.Color] = {
    "Бирюзовый (По умолчанию)": discord.Color.blurple(),
    "Красный": discord.Color.red(),
    "Зеленый": discord.Color.green(),
    "Синий": discord.Color.blue(),
    "Оранжевый": discord.Color.orange(),
    "Фиолетовый": discord.Color.purple(),
    "Золотой": discord.Color.gold(),
    "Серый": discord.Color.light_grey(),
    "Темно-красный": discord.Color.dark_red(),
    "Темно-синий": discord.Color.dark_blue(),
    "Почти черный": discord.Color.from_rgb(1, 1, 1),
}

#: SGR codes for the colours ``{color:name}`` accepts.
_ANSI_CODES = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "gray": "30",
    "grey": "30",
}

#: The escape byte that makes the sequence an actual ANSI code. Leaving it out
#: is what made this feature print a literal "[0;31m" instead of colouring the
#: text — Discord only recognises the sequence when it starts with ESC.
#: Written as an escape rather than a literal control byte so it survives
#: copy-paste and diffs.
_ESC = "\x1b"

_COLOR_TAG = re.compile(r"\{color:(\w+)\}(.*?)\{/color\}", re.DOTALL)


def expand_color_tags(text: str) -> str:
    """Turn ``{color:red}…{/color}`` into an ANSI-coloured code block.

    Discord renders colours only inside a ```ansi fence, so each tagged span
    becomes its own block. Unknown colour names fall back to the default
    foreground rather than failing.
    """

    def replace(match: re.Match[str]) -> str:
        code = _ANSI_CODES.get(match.group(1).lower(), "0")
        inner = match.group(2)
        return f"```ansi\n{_ESC}[0;{code}m{inner}{_ESC}[0m\n```"

    return _COLOR_TAG.sub(replace, text)


def parse_hex_color(value: str) -> discord.Color | None:
    """``#RGB`` / ``#RRGGBB`` -> a Colour, or None when it is not valid hex.

    The short form must be expanded first: ``int("f00", 16)`` is 0x000F00
    (dark green), not the red the user asked for.
    """
    if not re.fullmatch(r"#?(?:[0-9a-fA-F]{3}){1,2}", (value or "").strip()):
        return None
    digits = value.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return discord.Color(int(digits, 16))
