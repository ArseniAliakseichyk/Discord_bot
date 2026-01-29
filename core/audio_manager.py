"""
Оптимизированный аудио менеджер с prefetch и кэшированием.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from cachetools import TTLCache

import discord
from utils.yt_utils import fetch_info_sync, YDL_OPTS
import yt_dlp

logger = logging.getLogger(__name__)

# Кэш для метаданных (долгий TTL - 24 часа)
metadata_cache: TTLCache = TTLCache(maxsize=1000, ttl=86400)

# Кэш для готовых URL (короткий TTL - 5 часов, URL живут ~6 часов)
url_cache: TTLCache = TTLCache(maxsize=100, ttl=18000)

# Executor для фоновых задач
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audio_prefetch")

# Prefetch storage
_prefetched: Dict[str, Dict[str, Any]] = {}


@dataclass
class TrackInfo:
    """Информация о треке"""
    query: str  # YouTube URL или поисковый запрос
    title: str
    web_url: str
    thumbnail: str
    duration: str
    duration_seconds: int
    source: str  # 'youtube', 'spotify', 'local'
    requested_by_name: str
    requested_by_avatar: str
    audio_url: Optional[str] = None  # Заполняется при prefetch
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            'query': self.query,
            'title': self.title,
            'web_url': self.web_url,
            'thumbnail': self.thumbnail,
            'duration': self.duration,
            'duration_seconds': self.duration_seconds,
            'source': self.source,
            'requested_by_name': self.requested_by_name,
            'requested_by_avatar': self.requested_by_avatar,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TrackInfo':
        return cls(
            query=data.get('query', ''),
            title=data.get('title', 'Unknown'),
            web_url=data.get('web_url', ''),
            thumbnail=data.get('thumbnail', ''),
            duration=data.get('duration', 'N/A'),
            duration_seconds=data.get('duration_seconds', 0),
            source=data.get('source', 'youtube'),
            requested_by_name=data.get('requested_by_name', 'Unknown'),
            requested_by_avatar=data.get('requested_by_avatar', ''),
        )


def _fetch_fresh_url(query: str) -> Optional[str]:
    """Получает свежий аудио URL (синхронно, для executor)"""
    try:
        # Проверяем кэш URL
        if query in url_cache:
            logger.debug(f"URL cache hit for {query[:50]}")
            return url_cache[query]

        info = fetch_info_sync(query)
        if info and info.get('url'):
            url_cache[query] = info['url']
            return info['url']
    except Exception as e:
        logger.error(f"Error fetching URL for {query[:50]}: {e}")
    return None


async def prefetch_track(query: str) -> None:
    """Предзагружает URL трека в фоне"""
    if query in _prefetched:
        return

    loop = asyncio.get_running_loop()
    try:
        url = await loop.run_in_executor(_executor, _fetch_fresh_url, query)
        if url:
            _prefetched[query] = {
                'url': url,
                'fetched_at': time.time()
            }
            logger.info(f"Prefetched URL for: {query[:50]}")
    except Exception as e:
        logger.error(f"Prefetch error: {e}")


def get_prefetched_url(query: str, max_age: int = 3600) -> Optional[str]:
    """Получает prefetch URL если он свежий"""
    if query in _prefetched:
        data = _prefetched[query]
        age = time.time() - data['fetched_at']
        if age < max_age:
            del _prefetched[query]  # Удаляем после использования
            return data['url']
        else:
            del _prefetched[query]  # Устарел
    return None


def get_audio_url(query: str) -> str:
    """Получает аудио URL (из prefetch или свежий)"""
    # Сначала проверяем prefetch
    url = get_prefetched_url(query)
    if url:
        logger.info(f"Using prefetched URL for: {query[:50]}")
        return url

    # Иначе получаем свежий
    url = _fetch_fresh_url(query)
    if not url:
        raise ValueError(f"Could not get audio URL for: {query[:50]}")
    return url


def create_audio_source(audio_url: str, is_local: bool = False) -> discord.FFmpegPCMAudio:
    """Создает оптимизированный аудио источник"""
    if is_local:
        return discord.FFmpegPCMAudio(
            executable="ffmpeg",
            source=audio_url,
            options="-vn -b:a 128k"
        )

    # Оптимизированные опции для стриминга
    before_opts = (
        "-loglevel error "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-analyzeduration 0 -probesize 32768 "  # Быстрый старт
        "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'"
    )

    return discord.FFmpegPCMAudio(
        executable="ffmpeg",
        source=audio_url,
        before_options=before_opts,
        options="-vn -b:a 128k -bufsize 64k"  # Буфер для стабильности
    )


async def prepare_track_for_playback(track_dict: dict) -> discord.AudioSource:
    """Подготавливает трек к воспроизведению (async wrapper)"""
    import os
    from core import state

    query = track_dict.get('query', '')

    # Проверка на прямой googlevideo URL (legacy)
    if 'googlevideo.com' in query or 'videoplayback' in query:
        web_url = track_dict.get('web_url')
        if web_url and 'youtube.com' in web_url:
            query = web_url

    is_local = os.path.exists(query)

    if is_local:
        return create_audio_source(query, is_local=True)

    # Получаем URL (из prefetch или свежий)
    loop = asyncio.get_running_loop()
    audio_url = await loop.run_in_executor(state.executor, get_audio_url, query)

    source = create_audio_source(audio_url)
    return discord.PCMVolumeTransformer(source, volume=0.5)


def clear_caches():
    """Очищает все кэши"""
    metadata_cache.clear()
    url_cache.clear()
    _prefetched.clear()
