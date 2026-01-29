import yt_dlp
import asyncio
import logging
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)

cache = TTLCache(maxsize=2000, ttl=7200)

# Общие опции для yt-dlp
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
    'ignoreerrors': False,
    'extract_flat': False,
    'force_generic_extractor': False,
    'cookiefile': 'cookies.txt',
    'geo_bypass': True,
    'geo_bypass_country': 'US',
    'age_limit': 25,
    'socket_timeout': 10,
    'retries': 3,
    'http_chunk_size': 1048576,
    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
}

class AgeRestrictedError(Exception):
    pass

def is_retryable_exception(e):
    return not isinstance(e, AgeRestrictedError)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(is_retryable_exception)
)
async def fetch_info(query, is_search=False):
    if query in cache:
        logger.info(f"Cache hit for {query}")
        return cache[query]

    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            
            if not info:
                raise ValueError("Не удалось получить информацию о треке")
            
            if is_search and 'entries' in info:
                if info['entries']:
                    info = info['entries'][0]
                else:
                    raise ValueError("По вашему запросу ничего не найдено")
            elif 'entries' in info:
                raise ValueError("Плейлисты не поддерживаются")
            
            cache[query] = info
            return info
    except yt_dlp.utils.DownloadError as e:
        if "Sign in to confirm your age" in str(e):
            raise AgeRestrictedError("Видео недоступно из-за возрастных ограничений")
        else:
            logger.error(f"Ошибка получения информации: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Ошибка получения информации: {str(e)}")
        raise

def fetch_info_sync(query):
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            
            if not info:
                raise ValueError("Не удалось получить информацию о треке")
            
            if 'entries' in info:
                raise ValueError("Плейлисты не поддерживаются")
            
            return info
    except yt_dlp.utils.DownloadError as e:
        if "Sign in to confirm your age" in str(e):
            raise AgeRestrictedError("Видео недоступно из-за возрастных ограничений")
        else:
            logger.error(f"Синхронная ошибка: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Синхронная ошибка: {str(e)}")
        raise