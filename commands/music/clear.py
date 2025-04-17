import discord
from discord import app_commands
from core import state

@app_commands.command(name="clear", description="Очистить очередь")
async def clear_queue(interaction: discord.Interaction):
    state.queue.clear()
    await interaction.response.send_message("🧹 Очередь очищена.")