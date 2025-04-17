import discord
from config import settings

async def connect_to_voice(interaction):
    if interaction.user.voice:
        return await interaction.user.voice.channel.connect()
    await interaction.response.send_message("❌ Сначала подключитесь к голосовому каналу.")
    return None