import discord
from discord import app_commands
import os
from core import state
from core.voice import connect_to_voice
from config import settings

MAX_PLAYLIST_SIZE = 50

@app_commands.command(name="play", description="Проиграть музыку с YouTube или локального файла")
@app_commands.describe(query="Ссылка на YouTube или имя локального файла")
@app_commands.checks.cooldown(1, 5.0)
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    vc = interaction.guild.voice_client
    if not vc:
        vc = await connect_to_voice(interaction)
        if not vc:
            return

    queue = interaction.client.queue
    await queue.put((query.strip(), interaction, vc))