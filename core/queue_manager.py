import asyncio
import os
import logging
from core import state
from utils.yt_utils import fetch_info
from config import settings
from core.player import play_next
from tenacity import retry, stop_after_attempt, wait_exponential
import discord
from ui.controls import ControlButtons

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def format_duration(seconds: int) -> str:
    """Форматирует длительность в секундах в формат MM:SS или HH:MM:SS"""
    if seconds <= 0:
        return "00:00"
    
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def process_queue_item(query, interaction, vc):
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
        else:
            info = await fetch_info(query)
            
            if not info or not info.get('url'):
                raise ValueError("Не удалось получить аудио URL")
        
            duration_seconds = info.get('duration', 0)
            duration_str = format_duration(duration_seconds)
            
            track = {
                'query': info['url'],
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
        
        await interaction.followup.send(f"🎵 Добавлен трек: `{track['title']}`")
        
        if state.last_now_playing_message and state.current and vc and vc.is_connected():
            try:
                await state.last_now_playing_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            state.last_now_playing_message = None
            
            status = "▶️ Воспроизведение"
            if vc.is_paused():
                status = "⏸️ На паузе"
            elif state.looping:
                status = "🔁 Повтор"
        
            embed = discord.Embed(
                title="🎵 Сейчас играет",
                description=f"[{state.current['title']}]({state.current.get('web_url', 'https://youtube.com')})",
                color=discord.Color.green() if state.current.get('source') == 'local' else discord.Color.gold()
            )
            
            thumbnail = state.current.get('thumbnail', 'https://i.imgur.com/zG0SXqW.png')
            embed.set_thumbnail(url=thumbnail)
            
            embed.add_field(
                name="Длительность", 
                value=state.current.get('duration', 'N/A'),
                inline=True
            )
            
            embed.add_field(
                name="Источник", 
                value="Локальный файл" if state.current.get('source') == 'local' else "YouTube",
                inline=True
            )
            
            embed.add_field(
                name="Статус", 
                value=status,
                inline=True
            )
            
            requested_by = state.current.get('requested_by_name', 'Неизвестно')
            avatar_url = state.current.get('requested_by_avatar', 'https://i.imgur.com/7R5eEBd.png')
            
            embed.set_footer(
                text=f"Добавлено: {requested_by}",
                icon_url=avatar_url
            )
        
            state.last_now_playing_message = await interaction.channel.send(
                embed=embed, 
                view=ControlButtons(interaction.channel, play_next)
            )
        
        if vc and not vc.is_playing() and not vc.is_paused() and state.current is None:
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