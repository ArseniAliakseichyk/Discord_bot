import discord
from discord import app_commands
import os
import asyncio
from core import state
from core.voice import connect_to_voice
from utils.yt_utils import fetch_info
from core.player import play_next
from config import settings
from ui.controls import ControlButtons

async def process_playlist(entries, interaction):
    """Асинхронная обработка плейлиста с периодическим освобождением event loop"""
    try:
        added_tracks = 0
        for entry in entries:
            async with state.queue_lock:
                state.queue.append({'query': entry['webpage_url'], 'title': entry['title']})
            added_tracks += 1
            
            if added_tracks % 5 == 0:  # Отправляем промежуточные уведомления
                await interaction.followup.send(f"🎵 Добавлено треков: {added_tracks}/{len(entries)}")
                await asyncio.sleep(0.1)  # Даем время для обработки других событий
        
        await interaction.followup.send(f"✅ Успешно добавлено {len(entries)} треков из плейлиста!")
    except Exception as e:
        await interaction.followup.send(f"⚠️ Ошибка при обработке плейлиста: {str(e)}")

@app_commands.command(name="play", description="Проиграть музыку с YouTube или локального файла")
@app_commands.describe(query="Ссылка на YouTube или имя локального файла")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    try:
        vc = interaction.guild.voice_client or await connect_to_voice(interaction)
        if not vc: return

        query = query.strip()
        local_path = os.path.join(settings.MUSIC_FOLDER, query)

        if os.path.exists(local_path):
            async with state.queue_lock:
                state.queue.append({'query': local_path, 'title': query})
            await interaction.followup.send(f"🎵 Добавлен локальный файл: `{query}`")
        else:
            info = await fetch_info(query)
            if 'entries' in info:
                await interaction.followup.send(f"⏳ Начинаю обработку плейлиста ({len(info['entries'])} треков)...")
                asyncio.create_task(process_playlist(info['entries'], interaction))
            else:
                async with state.queue_lock:
                    state.queue.append({'query': query, 'title': info['title']})
                await interaction.followup.send(f"🎵 Добавлен трек: `{info['title']}`")

        if not vc.is_playing() and not vc.is_paused():
            await play_next(vc, interaction.channel)

    except Exception as e:
        await interaction.followup.send(f"⚠️ Критическая ошибка: {str(e)}")