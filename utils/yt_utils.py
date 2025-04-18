import yt_dlp
import asyncio
import logging
import time
from cachetools import TTLCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

cache = TTLCache(maxsize=1000, ttl=3600)

async def fetch_info(query):
    if query in cache:
        logger.info(f"Cache hit for {query}")
        return cache[query]

    start_time = time.time()
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'noplaylist': False,
        'extract_flat': True,
        'socket_timeout': 5,
        'http_chunk_size': 524288,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = await asyncio.to_thread(ydl.extract_info, query, download=False)
        cache[query] = info
        logger.info(f"fetch_info for {query} took {time.time() - start_time:.2f} seconds")
        return info

def fetch_info_sync(query):
    if query in cache:
        logger.info(f"Cache hit for {query}")
        return cache[query]

    start_time = time.time()
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'noplaylist': False,
        'extract_flat': True,
        'socket_timeout': 5,
        'http_chunk_size': 524288,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        cache[query] = info
        logger.info(f"fetch_info_sync for {query} took {time.time() - start_time:.2f} seconds")
        return info