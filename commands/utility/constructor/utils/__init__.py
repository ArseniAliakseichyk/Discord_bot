"""
Утилиты для конструктора embed.
"""

from .colors import PRESET_COLORS, parse_text_colors
from .validators import validate_embed, count_embed_chars, validate_url, get_embed_stats

__all__ = [
    'PRESET_COLORS',
    'parse_text_colors',
    'validate_embed',
    'count_embed_chars',
    'validate_url',
    'get_embed_stats',
]
