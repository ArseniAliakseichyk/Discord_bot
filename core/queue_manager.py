"""
Оптимизированный менеджер очереди с быстрым добавлением треков.
"""
import asyncio
import os
import logging
import re
import requests
from core import state
from utils.yt_utils import fetch_info, AgeRestrictedError
from config import settings
from core.player import play_next
from core.audio_manager import prefetch_track, metadata_cache
from tenacity import retry, stop_after_attempt, wait_exponential
import discord

logger = logging.getLogger(__name__)

# Импортируем os для проверки локальных файлов (уже есть выше)

def format_duration(seconds: int) -> str:
    """Форматирует длительность в секундах в формат MM:SS или HH:MM:SS"""
    if seconds <= 0:
        return "00:00"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

def fetch_spotify_title_sync(url: str) -> str:
    """
    Синхронно получает HTML страницы Spotify и извлекает <title>.
    Используется ваш метод.
    """
    logger.info(f"Fetching Spotify title from: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/91.0.4472.124 Safari/537.36'
        }
        html = requests.get(url, headers=headers, timeout=5, allow_redirects=True).text
        
        match = re.search(r"<title>(.*?)\s*\|\s*Spotify</title>", html, re.IGNORECASE | re.DOTALL)
        
        if match:
            title = match.group(1).strip()
            logger.info(f"Found Spotify title: {title}")
            return title
        else:
            logger.warning(f"Could not find <title> tag in Spotify response for {url}")
            raise ValueError("Не удалось найти тег <title> в Spotify")
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching Spotify URL {url}: {e}")
        raise ValueError(f"Ошибка сети при запросе Spotify: {e}")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def process_queue_item(query, interaction, vc):
    """Обрабатывает добавление трека в очередь"""
    try:
        local_path = os.path.join(settings.MUSIC_FOLDER, query)
        user_display = interaction.user.display_name
        user_avatar = interaction.user.display_avatar.url
        
        if os.path.exists(local_path):
            track = {
                'query': local_path,
                'title': os.path.basename(query),
                'source': 'local',
                'requested_by_name': user_display,
                'requested_by_avatar': user_avatar
            }
        
        elif "spotify.com" in query:
            try:
                loop = asyncio.get_running_loop()
                spotify_title = await loop.run_in_executor(state.executor, fetch_spotify_title_sync, query)
            except Exception as e:
                logger.error(f"Failed to fetch Spotify title: {e}", exc_info=True)
                await interaction.edit_original_response(content=f"⚠️ {str(e)}")
                return

            search_query = "ytsearch:" + spotify_title
            info = await fetch_info(search_query, is_search=True)

            if not info or not info.get('webpage_url'):
                raise ValueError(f"Не удалось найти трек '{spotify_title}' на YouTube")

            duration_seconds = info.get('duration', 0)
            duration_str = format_duration(duration_seconds)

            # Сохраняем webpage_url вместо url, чтобы получать свежий аудио URL при воспроизведении
            track = {
                'query': info.get('webpage_url'),
                'title': info.get('title', spotify_title),
                'web_url': info.get('webpage_url', 'https://youtube.com'),
                'thumbnail': info.get('thumbnail', 'https://i.imgur.com/zG0SXqW.png'),
                'duration': duration_str,
                'duration_seconds': duration_seconds,
                'source': 'spotify',
                'requested_by_name': user_display,
                'requested_by_avatar': user_avatar
            }

        else:
            if query.startswith("http://") or query.startswith("https://"):
                info = await fetch_info(query, is_search=False)
            else:
                search_query = "ytsearch:" + query
                info = await fetch_info(search_query, is_search=True)

            if not info or not info.get('webpage_url'):
                raise ValueError("Не удалось получить информацию о треке")

            duration_seconds = info.get('duration', 0)
            duration_str = format_duration(duration_seconds)

            # Сохраняем webpage_url вместо url, чтобы получать свежий аудио URL при воспроизведении
            track = {
                'query': info.get('webpage_url'),
                'title': info.get('title', 'Без названия'),
                'web_url': info.get('webpage_url', 'https://youtube.com'),
                'thumbnail': info.get('thumbnail', 'https://i.imgur.com/zG0SXqW.png'),
                'duration': duration_str,
                'duration_seconds': duration_seconds,
                'source': 'youtube',
                'requested_by_name': user_display,
                'requested_by_avatar': user_avatar
            }

        async with state.queue_lock:
            state.queue.append(track)
            queue_position = len(state.queue)

        # Быстрый ответ пользователю
        if queue_position == 1 and state.current is None:
            await interaction.edit_original_response(content=f"🎵 Играю: `{track['title']}`")
        else:
            await interaction.edit_original_response(
                content=f"🎵 Добавлено #{queue_position}: `{track['title']}`"
            )

        # Prefetch этого трека если он следующий или единственный
        if queue_position <= 2 and not os.path.exists(track['query']):
            asyncio.create_task(prefetch_track(track['query']))

        if vc and not vc.is_playing() and not vc.is_paused() and state.current is None:
            await play_next(vc, interaction.channel)
        elif state.last_now_playing_message and vc:
            from ui.controls import ControlButtons
            view = ControlButtons(interaction.channel, play_next)
            asyncio.create_task(view.update_embed(interaction))

    except AgeRestrictedError as e:
        await interaction.edit_original_response(content="⚠️ Видео недоступно из-за возрастных ограничений.")
        logger.error(f"Ошибка обработки: {str(e)}")
    except ValueError as e:
        error_msg = str(e)
        await interaction.edit_original_response(content=f"⚠️ {error_msg}")
        logger.error(f"Ошибка обработки: {error_msg}")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ошибка обработки: {error_msg}")
        await interaction.edit_original_response(content=f"⚠️ Произошла ошибка: {error_msg}")

async def process_pending_requests():
    """Фоновая задача для обработки pending_queue"""
    while True:
        async with state.queue_lock:
            if state.pending_queue:
                query, interaction, vc = state.pending_queue.pop(0)
            else:
                query = None

        if query:
            asyncio.create_task(process_queue_item(query, interaction, vc))

        await asyncio.sleep(1)

async def process_queue_requests(bot):
    """Настройка очереди и обработчиков"""
    queue = asyncio.Queue()

    async def worker():
        while True:
            query, interaction, vc = await queue.get()
            try:
                await process_queue_item(query, interaction, vc)
            finally:
                queue.task_done()

    asyncio.create_task(worker())
    asyncio.create_task(process_pending_requests())
    return queue