import discord
from discord import app_commands
from core import state

@app_commands.command(name="now", description="Показать текущий трек")
async def now_playing(interaction: discord.Interaction):
    if state.current:
        await interaction.response.send_message(f"🎵 Сейчас играет: `{state.current['title']}`")
    else:
        await interaction.response.send_message("❌ Сейчас ничего не играет.")