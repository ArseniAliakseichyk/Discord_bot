import discord
from discord import app_commands
from core import state

@app_commands.command(name="queue", description="Показать очередь")
async def show_queue(interaction: discord.Interaction):
    if state.queue:
        msg = "\n".join([f"{i+1}. {track['title']}" for i, track in enumerate(state.queue)])
        await interaction.response.send_message(f"📜 Очередь:\n{msg}")
    else:
        await interaction.response.send_message("🚫 Очередь пуста.")