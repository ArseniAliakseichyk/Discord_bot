import discord
from discord import app_commands
import os
from core import state
from core.voice import connect_to_voice
from utils.yt_utils import fetch_info
from core.player import play_next
from config import settings
from ui.controls import ControlButtons

@app_commands.command(name="play", description="Проиграть музыку с YouTube или локального файла")
@app_commands.describe(query="Ссылка на YouTube или имя локального файла")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    vc = interaction.guild.voice_client
    if not vc:
        vc = await connect_to_voice(interaction)
        if not vc: return

    query = query.strip()
    local_path = os.path.join(settings.MUSIC_FOLDER, query)

    if os.path.exists(local_path):
        track = {'query': local_path, 'title': query}
        state.queue.append(track)
        await interaction.followup.send(f"🎵 Добавлен в очередь: `{query}`")
    else:
        try:
            info = await fetch_info(query)
            if 'entries' in info:
                await interaction.followup.send(f"🎵 Добавлено треков из плейлиста: {len(info['entries'])}")
                for entry in info['entries']:
                    state.queue.append({'query': entry['webpage_url'], 'title': entry['title']})
            else:
                track = {'query': query, 'title': info['title']}
                state.queue.append(track)
                await interaction.followup.send(f"🎵 Добавлен в очередь: `{info['title']}`")
        except Exception as e:
            await interaction.followup.send(f"⚠️ Ошибка: {str(e)}")
            return

    if not vc.is_playing() and not vc.is_paused():
        await play_next(vc, interaction.channel)