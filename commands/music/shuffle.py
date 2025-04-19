import discord
from discord import app_commands
import random
from core import state

@app_commands.command(name="shuffle", description="Перемешать очередь")
async def shuffle_queue(interaction: discord.Interaction):
    async with state.queue_lock:
        if state.queue:
            random.shuffle(state.queue)
            await interaction.response.send_message("🔀 Очередь перемешана.")
        else:
            await interaction.response.send_message("🚫 Очередь пуста.")