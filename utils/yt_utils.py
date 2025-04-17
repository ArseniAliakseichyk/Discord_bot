import yt_dlp
import asyncio

async def fetch_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'noplaylist': True,
        'socket_timeout': 10,
        'http_chunk_size': 1048576,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return await asyncio.to_thread(ydl.extract_info, query, download=False)