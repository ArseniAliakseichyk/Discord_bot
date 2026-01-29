"""
Валидация embed и подсчёт лимитов Discord.
"""
import re
from typing import Tuple, List, Dict
import discord

from ..constants import (
    TITLE_MAX, DESCRIPTION_MAX, FIELD_NAME_MAX, FIELD_VALUE_MAX,
    FOOTER_MAX, AUTHOR_NAME_MAX, FIELDS_MAX, TOTAL_CHARS_MAX
)


def count_embed_chars(embed: discord.Embed) -> int:
    """
    Подсчитывает общее количество символов в embed.
    Discord лимит: 6000 символов на embed.
    """
    total = 0

    if embed.title:
        total += len(embed.title)
    if embed.description:
        total += len(embed.description)
    if embed.footer and embed.footer.text:
        total += len(embed.footer.text)
    if embed.author and embed.author.name:
        total += len(embed.author.name)

    for field in embed.fields:
        total += len(field.name) + len(field.value)

    return total


def get_embed_stats(embed: discord.Embed) -> Dict[str, str]:
    """
    Возвращает статистику использования лимитов embed.

    Returns:
        Dict с ключами: title, description, footer, author, fields, total
    """
    stats = {}

    # Title
    title_len = len(embed.title) if embed.title else 0
    stats['title'] = f"{title_len}/{TITLE_MAX}"

    # Description
    desc_len = len(embed.description) if embed.description else 0
    stats['description'] = f"{desc_len}/{DESCRIPTION_MAX}"

    # Footer
    footer_len = len(embed.footer.text) if embed.footer and embed.footer.text else 0
    stats['footer'] = f"{footer_len}/{FOOTER_MAX}"

    # Author
    author_len = len(embed.author.name) if embed.author and embed.author.name else 0
    stats['author'] = f"{author_len}/{AUTHOR_NAME_MAX}"

    # Fields
    fields_count = len(embed.fields)
    stats['fields'] = f"{fields_count}/{FIELDS_MAX}"

    # Total
    total = count_embed_chars(embed)
    stats['total'] = f"{total}/{TOTAL_CHARS_MAX}"

    return stats


def validate_embed(embed: discord.Embed) -> Tuple[bool, List[str]]:
    """
    Проверяет embed на соответствие лимитам Discord.

    Returns:
        (is_valid, list_of_errors)
    """
    errors = []

    # Title
    if embed.title and len(embed.title) > TITLE_MAX:
        errors.append(f"Заголовок слишком длинный: {len(embed.title)}/{TITLE_MAX}")

    # Description
    if embed.description and len(embed.description) > DESCRIPTION_MAX:
        errors.append(f"Описание слишком длинное: {len(embed.description)}/{DESCRIPTION_MAX}")

    # Footer
    if embed.footer and embed.footer.text and len(embed.footer.text) > FOOTER_MAX:
        errors.append(f"Футер слишком длинный: {len(embed.footer.text)}/{FOOTER_MAX}")

    # Author
    if embed.author and embed.author.name and len(embed.author.name) > AUTHOR_NAME_MAX:
        errors.append(f"Имя автора слишком длинное: {len(embed.author.name)}/{AUTHOR_NAME_MAX}")

    # Fields count
    if len(embed.fields) > FIELDS_MAX:
        errors.append(f"Слишком много полей: {len(embed.fields)}/{FIELDS_MAX}")

    # Field content
    for i, field in enumerate(embed.fields):
        if len(field.name) > FIELD_NAME_MAX:
            errors.append(f"Поле #{i+1}: название слишком длинное ({len(field.name)}/{FIELD_NAME_MAX})")
        if len(field.value) > FIELD_VALUE_MAX:
            errors.append(f"Поле #{i+1}: значение слишком длинное ({len(field.value)}/{FIELD_VALUE_MAX})")

    # Total chars
    total = count_embed_chars(embed)
    if total > TOTAL_CHARS_MAX:
        errors.append(f"Общий лимит символов превышен: {total}/{TOTAL_CHARS_MAX}")

    return (len(errors) == 0, errors)


def validate_url(url: str) -> bool:
    """
    Проверяет валидность URL.
    """
    if not url:
        return True  # Пустой URL валиден (опциональное поле)

    pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    return bool(pattern.match(url))


def get_warnings(embed: discord.Embed) -> List[str]:
    """
    Возвращает предупреждения о приближении к лимитам (80%+).
    """
    warnings = []

    # Title
    if embed.title:
        usage = len(embed.title) / TITLE_MAX
        if usage >= 0.8:
            warnings.append(f"⚠️ Заголовок: {int(usage*100)}% лимита")

    # Description
    if embed.description:
        usage = len(embed.description) / DESCRIPTION_MAX
        if usage >= 0.8:
            warnings.append(f"⚠️ Описание: {int(usage*100)}% лимита")

    # Total
    total = count_embed_chars(embed)
    usage = total / TOTAL_CHARS_MAX
    if usage >= 0.8:
        warnings.append(f"⚠️ Общий лимит: {int(usage*100)}%")

    return warnings
