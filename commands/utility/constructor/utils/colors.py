"""
Управление цветами для embed.
"""
import re
from typing import Dict
import discord

# ===================================================================
# ПРЕСЕТЫ ЦВЕТОВ
# ===================================================================

PRESET_COLORS: Dict[str, discord.Color] = {
    "Бирюзовый (По умолчанию)": discord.Color.blurple(),
    "Красный": discord.Color.red(),
    "Зеленый": discord.Color.green(),
    "Синий": discord.Color.blue(),
    "Оранжевый": discord.Color.orange(),
    "Фиолетовый": discord.Color.purple(),
    "Золотой": discord.Color.gold(),
    "Розовый": discord.Color.magenta(),
    "Серый": discord.Color.light_grey(),
    "Темно-красный": discord.Color.dark_red(),
    "Темно-синий": discord.Color.dark_blue(),
    "Темно-зеленый": discord.Color.dark_green(),
    "Почти черный": discord.Color.from_rgb(1, 1, 1),
    "Белый": discord.Color.from_rgb(255, 255, 255),
}


def parse_text_colors(text: str) -> str:
    """
    Парсит кастомные теги {color:...} и превращает их в цветной текст для Discord.

    Пример: {color:red}Привет!{/color}

    Поддерживаемые цвета: red, green, yellow, blue, magenta, cyan, white
    """
    color_map = {
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "white": "37",
        "gray": "30",
        "orange": "33",  # yellow как fallback
    }

    def replace_color(match):
        color_name = match.group(1).lower()
        inner_text = match.group(2)
        code = color_map.get(color_name, "0")
        return f"```ansi\n\u001b[0;{code}m{inner_text}\n```"

    pattern = r'\{color:(\w+)\}(.*?)\{\/color\}'
    return re.sub(pattern, replace_color, text, flags=re.DOTALL)


def hex_to_color(hex_string: str) -> discord.Color:
    """
    Конвертирует HEX строку в discord.Color.

    Args:
        hex_string: Цвет в формате #RRGGBB или RRGGBB

    Returns:
        discord.Color

    Raises:
        ValueError: Если формат неверный
    """
    hex_color = hex_string.strip().lstrip("#")
    if len(hex_color) != 6:
        raise ValueError(f"Неверный формат HEX: {hex_string}")

    try:
        return discord.Color(int(hex_color, 16))
    except ValueError:
        raise ValueError(f"Неверный HEX цвет: {hex_string}")


def color_to_hex(color: discord.Color) -> str:
    """Конвертирует discord.Color в HEX строку."""
    return f"#{color.value:06x}"
