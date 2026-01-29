"""
Система шаблонов для embed.
Сохранение и загрузка шаблонов в JSON.
"""
import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..constants import TEMPLATES_DIR

logger = logging.getLogger(__name__)


def ensure_templates_dir():
    """Создаёт папку для шаблонов если её нет."""
    if not os.path.exists(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        logger.info(f"Created templates directory: {TEMPLATES_DIR}")


def embed_to_dict(embed) -> Dict[str, Any]:
    """Конвертирует discord.Embed в словарь для сохранения."""
    data = {
        "title": embed.title,
        "description": embed.description,
        "url": embed.url,
        "color": embed.color.value if embed.color else None,
        "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
        "fields": [
            {
                "name": field.name,
                "value": field.value,
                "inline": field.inline
            }
            for field in embed.fields
        ]
    }

    if embed.author:
        data["author"] = {
            "name": embed.author.name,
            "url": embed.author.url,
            "icon_url": embed.author.icon_url
        }

    if embed.footer:
        data["footer"] = {
            "text": embed.footer.text,
            "icon_url": embed.footer.icon_url
        }

    if embed.image:
        data["image"] = {"url": embed.image.url}

    if embed.thumbnail:
        data["thumbnail"] = {"url": embed.thumbnail.url}

    return data


def dict_to_embed(data: Dict[str, Any]):
    """Конвертирует словарь обратно в discord.Embed."""
    import discord

    embed = discord.Embed(
        title=data.get("title"),
        description=data.get("description"),
        url=data.get("url"),
        color=discord.Color(data["color"]) if data.get("color") else None
    )

    if data.get("timestamp"):
        embed.timestamp = datetime.fromisoformat(data["timestamp"])

    for field in data.get("fields", []):
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False)
        )

    if data.get("author"):
        embed.set_author(
            name=data["author"].get("name", ""),
            url=data["author"].get("url"),
            icon_url=data["author"].get("icon_url")
        )

    if data.get("footer"):
        embed.set_footer(
            text=data["footer"].get("text", ""),
            icon_url=data["footer"].get("icon_url")
        )

    if data.get("image"):
        embed.set_image(url=data["image"]["url"])

    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"]["url"])

    return embed


def save_template(
    name: str,
    embed,
    buttons: List[Dict] = None,
    message_content: str = None
) -> bool:
    """
    Сохраняет шаблон в файл.

    Args:
        name: Название шаблона
        embed: discord.Embed
        buttons: Список кнопок
        message_content: Текст сообщения

    Returns:
        True если успешно
    """
    ensure_templates_dir()

    # Санитизация имени файла
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_name:
        return False

    filename = os.path.join(TEMPLATES_DIR, f"{safe_name}.json")

    template_data = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "embed": embed_to_dict(embed),
        "buttons": buttons or [],
        "message_content": message_content
    }

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(template_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Template saved: {name}")
        return True
    except Exception as e:
        logger.error(f"Failed to save template {name}: {e}")
        return False


def load_template(name: str) -> Optional[Dict[str, Any]]:
    """
    Загружает шаблон из файла.

    Returns:
        Dict с ключами: embed, buttons, message_content или None
    """
    ensure_templates_dir()

    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
    filename = os.path.join(TEMPLATES_DIR, f"{safe_name}.json")

    if not os.path.exists(filename):
        return None

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return {
            "embed": dict_to_embed(data["embed"]),
            "buttons": data.get("buttons", []),
            "message_content": data.get("message_content"),
            "name": data.get("name", name),
            "created_at": data.get("created_at")
        }
    except Exception as e:
        logger.error(f"Failed to load template {name}: {e}")
        return None


def list_templates() -> List[str]:
    """
    Возвращает список доступных шаблонов.

    Returns:
        Список названий шаблонов
    """
    ensure_templates_dir()

    templates = []
    try:
        for filename in os.listdir(TEMPLATES_DIR):
            if filename.endswith('.json'):
                templates.append(filename[:-5])  # Убираем .json
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")

    return sorted(templates)


def delete_template(name: str) -> bool:
    """
    Удаляет шаблон.

    Returns:
        True если успешно
    """
    ensure_templates_dir()

    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
    filename = os.path.join(TEMPLATES_DIR, f"{safe_name}.json")

    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Template deleted: {name}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete template {name}: {e}")
        return False


# ===================================================================
# ПРЕДУСТАНОВЛЕННЫЕ ШАБЛОНЫ
# ===================================================================

DEFAULT_TEMPLATES = {
    "Анонс": {
        "title": "📢 Важное объявление",
        "description": "Здесь текст вашего объявления...",
        "color": 0x5865F2,
        "fields": []
    },
    "Правила": {
        "title": "📜 Правила сервера",
        "description": "Добро пожаловать! Пожалуйста, ознакомьтесь с правилами.",
        "color": 0x57F287,
        "fields": [
            {"name": "1️⃣ Уважение", "value": "Уважайте других участников.", "inline": False},
            {"name": "2️⃣ Спам", "value": "Запрещён спам и флуд.", "inline": False},
            {"name": "3️⃣ Контент", "value": "Только допустимый контент.", "inline": False}
        ]
    },
    "Событие": {
        "title": "🎉 Событие",
        "description": "Приглашаем вас на мероприятие!",
        "color": 0xFEE75C,
        "fields": [
            {"name": "📅 Дата", "value": "Укажите дату", "inline": True},
            {"name": "⏰ Время", "value": "Укажите время", "inline": True},
            {"name": "📍 Место", "value": "Укажите место", "inline": True}
        ]
    }
}


def get_default_template(name: str):
    """Возвращает предустановленный шаблон."""
    import discord

    if name not in DEFAULT_TEMPLATES:
        return None

    data = DEFAULT_TEMPLATES[name]
    embed = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=discord.Color(data["color"])
    )

    for field in data.get("fields", []):
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False)
        )

    return embed
