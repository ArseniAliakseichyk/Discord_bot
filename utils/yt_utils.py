import yt_dlp
import asyncio
import logging
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

cache = TTLCache(maxsize=1000, ttl=3600)

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