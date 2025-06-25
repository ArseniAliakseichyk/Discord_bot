import discord
from discord import app_commands
from core.voice import connect_to_voice
from core import state

@app_commands.command(name="play", description="Воспроизвести трек с YouTube или локальный файл")
@app_commands.describe(query="Ссылка на YouTube видео или имя локального файла")
@app_commands.checks.cooldown(1, 5.0)
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    if "list=" in query.lower():
        await interaction.followup.send("⚠️ Воспроизведение плейлистов отключено")
        return
        
    vc = interaction.guild.voice_client
    if not vc:
        vc = await connect_to_voice(interaction)
        if not vc:
            return
    
    async with state.queue_lock:
        state.pending_queue.append((query.strip(), interaction, vc))
    
    await interaction.followup.send("⏳ Обрабатываю ваш запрос...")