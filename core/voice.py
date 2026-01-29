import discord
from config import settings
from core import state

async def _send_error(interaction: discord.Interaction, message: str):
    """Отправляет сообщение об ошибке, учитывая состояние interaction."""
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

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
            await _send_error(interaction, f"❌ Не удалось подключиться к каналу `{channel.name}`: {str(e)}")
            return None
    else:
        if interaction.user.voice:
            try:
                return await interaction.user.voice.channel.connect()
            except Exception as e:
                await _send_error(interaction, f"❌ Не удалось подключиться: {str(e)}")
                return None
        await _send_error(interaction, "❌ Сначала подключитесь к голосовому каналу.")
        return None