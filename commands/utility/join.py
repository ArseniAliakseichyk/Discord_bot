import discord
from discord import app_commands
from core.voice import connect_to_voice

@app_commands.command(name="join", description="Подключить бота к голосовому каналу")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Сначала подключитесь к голосовому каналу.", ephemeral=True)
        return

    channel_name = interaction.user.voice.channel.name
    vc = interaction.guild.voice_client

    if vc and vc.is_connected():
        if vc.channel.id == interaction.user.voice.channel.id:
            await interaction.response.send_message(f"✅ Уже подключен к `{channel_name}`", ephemeral=True)
            return
        await vc.move_to(interaction.user.voice.channel)
        await interaction.response.send_message(f"🔊 Переместился в `{channel_name}`")
    else:
        vc = await connect_to_voice(interaction)
        if vc:
            await interaction.response.send_message(f"🔊 Подключился к `{channel_name}`")