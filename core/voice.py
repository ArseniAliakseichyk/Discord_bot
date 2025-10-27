import discord
from config import settings
from core import state

async def connect_to_voice(interaction: discord.Interaction, channel: discord.VoiceChannel = None):
    """
    Подключение бота к голосовому каналу.
    Если channel указан, подключается к нему. Иначе — к каналу пользователя.
    """
    if interaction.guild:
        state.last_text_channels[interaction.guild.id] = interaction.channel
    
    if channel:
        try:
            return await channel.connect()
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Не удалось подключиться к каналу `{channel.name}`: {str(e)}",
                ephemeral=True
            )
            return None
    else:
        if interaction.user.voice:
            return await interaction.user.voice.channel.connect()
        await interaction.response.send_message(
            "❌ Сначала подключитесь к голосовому каналу.",
            ephemeral=True
        )
        return None