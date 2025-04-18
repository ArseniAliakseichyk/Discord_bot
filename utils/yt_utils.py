import yt_dlp
import asyncio

ytdl_semaphore = asyncio.Semaphore(3)

async def fetch_info(query):
    async with ytdl_semaphore:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'noplaylist': False,
            'socket_timeout': 10,
            'http_chunk_size': 1048576,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return await asyncio.to_thread(ydl.extract_info, query, download=False)