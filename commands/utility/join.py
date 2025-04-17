import discord
from discord import app_commands
from core.voice import connect_to_voice

@app_commands.command(name="join", description="Подключить бота к голосовому каналу")
async def join(interaction: discord.Interaction):
    vc = await connect_to_voice(interaction)
    if vc:
        await interaction.response.send_message(f"🔊 Подключился к `{interaction.user.voice.channel.name}`")