import discord
from discord import app_commands
from core import state

@app_commands.command(name="leave", description="Отключить бота от голосового канала")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        state.queue.clear()
        if state.last_now_playing_message:
            try:
                await state.last_now_playing_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            state.last_now_playing_message = None
        await interaction.response.send_message("👋 Отключился и очистил очередь.")
    else:
        await interaction.response.send_message("❌ Бот не в голосовом канале.")