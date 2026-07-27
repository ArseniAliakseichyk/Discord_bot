"""Shared constants: embed styling, Discord API limits and repeated user messages.

Kept in one place so a value that appears in several cogs is defined once.
"""

from __future__ import annotations

#: Default embed colour (matches Discord's dark background).
EMBED_COLOR = 0x2B2D31

# --- Discord API limits -------------------------------------------------- #
EMBED_DESC_LIMIT = 4000
FIELD_VALUE_LIMIT = 1024
SELECT_LABEL_LIMIT = 100
MAX_EMBED_FIELDS = 25
MESSAGE_LIMIT = 2000

# --- View timeouts, seconds ---------------------------------------------- #
SEARCH_TIMEOUT = 60
IMAGE_ACTION_TIMEOUT = 180
PREVIEW_TIMEOUT = 300
BUILDER_TIMEOUT = 3600

# --- Repeated user-facing messages --------------------------------------- #
MSG_JOIN_VOICE_FIRST = "❌ Сначала зайдите в голосовой канал."
MSG_BOT_NOT_CONNECTED = "❌ Бот не в голосовом канале."
MSG_QUEUE_EMPTY = "🚫 Очередь пуста."
MSG_NEED_DJ = "❌ Нужна DJ-роль для управления воспроизведением."
MSG_NOTHING_PLAYING = "🚫 Сейчас ничего не играет."
