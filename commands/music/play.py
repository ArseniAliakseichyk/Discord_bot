import discord
from discord import app_commands
from core.voice import connect_to_voice

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

    queue = interaction.client.queue
    await queue.put((query.strip(), interaction, vc))