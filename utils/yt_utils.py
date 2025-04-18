import yt_dlp
import asyncio
import logging
import time
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

cache = TTLCache(maxsize=1000, ttl=3600)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_info(query):
    if query in cache:
        logger.info(f"Cache hit for {query}")
        return cache[query]

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'ignoreerrors': False,
        'extract_flat': False,
        'force_generic_extractor': False,
        'cookiefile': 'cookies.txt',
        'geo_bypass': True,
        'age_limit': 25,
        'socket_timeout': 5,
        'http_chunk_size': 524288
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            
            if not info:
                raise ValueError("Не удалось получить информацию о треке")

            if 'entries' in info:
                raise ValueError("Плейлисты не поддерживаются")

            cache[query] = info
            return info
    except Exception as e:
        logger.error(f"Ошибка получения информации: {str(e)}")
        raise

def fetch_info_sync(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'ignoreerrors': False,
        'extract_flat': False,
        'force_generic_extractor': False,
        'cookiefile': 'cookies.txt',
        'geo_bypass': True,
        'age_limit': 25,
        'socket_timeout': 5,
        'http_chunk_size': 524288
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)
    except Exception as e:
        logger.error(f"Синхронная ошибка: {str(e)}")
        raise