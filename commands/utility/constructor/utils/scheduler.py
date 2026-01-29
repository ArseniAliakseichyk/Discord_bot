"""
Планировщик отложенных публикаций.
"""
import discord
import asyncio
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid

from ..constants import TEMPLATES_DIR
from .templates import embed_to_dict, dict_to_embed

logger = logging.getLogger(__name__)

# Хранилище запланированных задач
_scheduled_tasks: Dict[str, asyncio.Task] = {}
_scheduled_data: Dict[str, 'ScheduledMessage'] = {}

# Файл для персистентности
SCHEDULE_FILE = os.path.join(TEMPLATES_DIR, "..", "scheduled_messages.json")


@dataclass
class ScheduledMessage:
    """Запланированное сообщение."""
    id: str
    channel_id: int
    guild_id: int
    author_id: int
    publish_at: str  # ISO format
    embed_data: Dict[str, Any]
    message_content: Optional[str] = None
    buttons: Optional[List[Dict]] = None
    create_thread: bool = False
    thread_name: Optional[str] = None
    role_mention_id: Optional[int] = None

    @property
    def publish_datetime(self) -> datetime:
        return datetime.fromisoformat(self.publish_at)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScheduledMessage':
        return cls(**data)


def _ensure_dir():
    """Создаёт директорию для файла расписания."""
    dir_path = os.path.dirname(SCHEDULE_FILE)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


def _save_scheduled():
    """Сохраняет расписание в файл."""
    _ensure_dir()
    try:
        data = [msg.to_dict() for msg in _scheduled_data.values()]
        with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save schedule: {e}")


def _load_scheduled() -> List[ScheduledMessage]:
    """Загружает расписание из файла."""
    _ensure_dir()
    if not os.path.exists(SCHEDULE_FILE):
        return []

    try:
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [ScheduledMessage.from_dict(d) for d in data]
    except Exception as e:
        logger.error(f"Failed to load schedule: {e}")
        return []


async def schedule_message(
    client: discord.Client,
    channel: discord.TextChannel,
    embed: discord.Embed,
    publish_at: datetime,
    author_id: int,
    message_content: Optional[str] = None,
    buttons: Optional[List[Dict]] = None,
    create_thread: bool = False,
    thread_name: Optional[str] = None,
    role_to_mention: Optional[discord.Role] = None
) -> str:
    """
    Планирует публикацию сообщения.

    Returns:
        ID задачи
    """
    task_id = str(uuid.uuid4())[:8]

    scheduled = ScheduledMessage(
        id=task_id,
        channel_id=channel.id,
        guild_id=channel.guild.id,
        author_id=author_id,
        publish_at=publish_at.isoformat(),
        embed_data=embed_to_dict(embed),
        message_content=message_content,
        buttons=buttons,
        create_thread=create_thread,
        thread_name=thread_name,
        role_mention_id=role_to_mention.id if role_to_mention else None
    )

    _scheduled_data[task_id] = scheduled
    _save_scheduled()

    # Создаём задачу
    delay = (publish_at - datetime.now()).total_seconds()
    if delay > 0:
        task = asyncio.create_task(_execute_scheduled(client, task_id, delay))
        _scheduled_tasks[task_id] = task
        logger.info(f"Scheduled message {task_id} for {publish_at}")
    else:
        # Если время уже прошло, публикуем сразу
        asyncio.create_task(_execute_scheduled(client, task_id, 0))

    return task_id


async def _execute_scheduled(client: discord.Client, task_id: str, delay: float):
    """Выполняет запланированную публикацию."""
    try:
        if delay > 0:
            await asyncio.sleep(delay)

        if task_id not in _scheduled_data:
            return  # Было отменено

        msg_data = _scheduled_data[task_id]

        # Получаем канал
        channel = client.get_channel(msg_data.channel_id)
        if not channel:
            try:
                channel = await client.fetch_channel(msg_data.channel_id)
            except discord.NotFound:
                logger.error(f"Channel {msg_data.channel_id} not found for scheduled message {task_id}")
                return

        # Восстанавливаем embed
        embed = dict_to_embed(msg_data.embed_data)

        # Подготовка контента
        content = msg_data.message_content or ""
        if msg_data.role_mention_id:
            guild = channel.guild
            role = guild.get_role(msg_data.role_mention_id)
            if role:
                content = f"{role.mention} {content}".strip()

        # Подготовка кнопок
        view = None
        if msg_data.buttons:
            from ..views.button_builder import create_button_view
            view = create_button_view(msg_data.buttons, client)

        # Публикация
        published = await channel.send(
            content=content or None,
            embed=embed,
            view=view
        )

        # Создание треда
        if msg_data.create_thread and msg_data.thread_name:
            await published.create_thread(
                name=msg_data.thread_name,
                auto_archive_duration=1440
            )

        logger.info(f"Scheduled message {task_id} published successfully")

    except Exception as e:
        logger.error(f"Failed to publish scheduled message {task_id}: {e}", exc_info=True)
    finally:
        # Очистка
        if task_id in _scheduled_data:
            del _scheduled_data[task_id]
        if task_id in _scheduled_tasks:
            del _scheduled_tasks[task_id]
        _save_scheduled()


async def cancel_scheduled(task_id: str) -> bool:
    """
    Отменяет запланированную публикацию.

    Returns:
        True если успешно
    """
    if task_id in _scheduled_tasks:
        _scheduled_tasks[task_id].cancel()
        del _scheduled_tasks[task_id]

    if task_id in _scheduled_data:
        del _scheduled_data[task_id]
        _save_scheduled()
        logger.info(f"Cancelled scheduled message {task_id}")
        return True

    return False


def get_scheduled_messages(guild_id: int) -> List[ScheduledMessage]:
    """Возвращает список запланированных сообщений для гильдии."""
    return [
        msg for msg in _scheduled_data.values()
        if msg.guild_id == guild_id
    ]


async def restore_scheduled_tasks(client: discord.Client):
    """
    Восстанавливает запланированные задачи после перезапуска бота.
    Вызывается в on_ready.
    """
    messages = _load_scheduled()
    now = datetime.now()

    for msg in messages:
        _scheduled_data[msg.id] = msg

        delay = (msg.publish_datetime - now).total_seconds()
        if delay > 0:
            task = asyncio.create_task(_execute_scheduled(client, msg.id, delay))
            _scheduled_tasks[msg.id] = task
            logger.info(f"Restored scheduled message {msg.id}")
        else:
            # Время прошло, публикуем сразу
            asyncio.create_task(_execute_scheduled(client, msg.id, 0))

    if messages:
        logger.info(f"Restored {len(messages)} scheduled messages")
