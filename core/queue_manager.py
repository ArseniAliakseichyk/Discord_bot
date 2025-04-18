import asyncio
import os
import logging
from core import state
from utils.yt_utils import fetch_info
from config import settings
from core.player import play_next
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def process_queue_item(query, interaction, vc):
    try:
        local_path = os.path.join(settings.MUSIC_FOLDER, query)
        
        if os.path.exists(local_path):
            track = {'query': local_path, 'title': os.path.basename(query)}
            state.queue.append(track)
            await interaction.followup.send(f"🎵 Добавлен локальный файл: `{os.path.basename(query)}`")
            return

        info = await fetch_info(query)
        
        if not info or not info.get('url'):
            raise ValueError("Не удалось получить аудио URL")

        track = {
            'query': info['url'],
            'title': info.get('title', 'Без названия')
        }
        
        state.queue.append(track)
        await interaction.followup.send(f"🎵 Добавлен трек: `{track['title']}`")

        if vc and not vc.is_playing() and not vc.is_paused():
            await play_next(vc, interaction.channel)

    except Exception as e:
        error_msg = str(e)
        if "Плейлисты не поддерживаются" in error_msg:
            error_msg = "⚠️ Плейлисты отключены"
        logger.error(f"Ошибка обработки: {error_msg}")
        await interaction.followup.send(f"❌ {error_msg}")
        raise

async def process_queue_requests(bot):
    queue = asyncio.Queue()

    async def worker():
        while True:
            query, interaction, vc = await queue.get()
            try:
                await process_queue_item(query, interaction, vc)
            finally:
                queue.task_done()

    asyncio.create_task(worker())
    return queue