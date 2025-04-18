import asyncio
import os
import logging
from core import state
from utils.yt_utils import fetch_info
from config import settings
from core.player import play_next

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_PLAYLIST_SIZE = 50

async def process_queue_requests(bot):
    queue = asyncio.Queue()

    async def worker():
        while True:
            query, interaction, vc = await queue.get()
            try:
                logger.info(f"Processing query: {query}")
                local_path = os.path.join(settings.MUSIC_FOLDER, query)
                if os.path.exists(local_path):
                    track = {'query': local_path, 'title': query}
                    state.queue.append(track)
                    logger.info(f"Added local track to queue: {track}")
                    await interaction.followup.send(f"🎵 Добавлен в очередь: `{query}`")
                else:
                    info = await fetch_info(query)
                    if 'entries' in info:
                        entries = info['entries'][:MAX_PLAYLIST_SIZE]
                        for entry in entries:
                            track_url = entry.get('url') or entry.get('webpage_url') or entry.get('id')
                            track_title = entry.get('title', 'Unknown Title')
                            if track_url:
                                state.queue.append({'query': track_url, 'title': track_title})
                                logger.info(f"Added playlist track to queue: {track_title} ({track_url})")
                            else:
                                logger.warning(f"Skipping playlist entry due to missing URL: {entry}")
                        await interaction.followup.send(f"🎵 Добавлено треков: {len(entries)} (ограничено {MAX_PLAYLIST_SIZE})")
                    else:
                        track = {'query': query, 'title': info.get('title', 'Unknown Title')}
                        state.queue.append(track)
                        logger.info(f"Added single track to queue: {track}")
                        await interaction.followup.send(f"🎵 Добавлен в очередь: `{info.get('title', 'Unknown Title')}`")

                logger.info(f"Current queue: {[track['title'] for track in state.queue]}")
                if vc and not vc.is_playing() and not vc.is_paused():
                    logger.info(f"Voice client state: playing={vc.is_playing()}, paused={vc.is_paused()}")
                    await play_next(vc, interaction.channel)
                else:
                    logger.warning("Voice client is not ready or already playing/paused")
            except Exception as e:
                logger.error(f"Error processing queue item: {str(e)}", exc_info=True)
                await interaction.followup.send(f"⚠️ Ошибка: {str(e)}")
            finally:
                queue.task_done()

    asyncio.create_task(worker())
    return queue