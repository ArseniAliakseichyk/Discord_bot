import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
from config import settings
from commands.register import register_commands
from core.queue_manager import process_queue_requests

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

bot = commands.Bot(command_prefix='/', intents=settings.INTENTS)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user.name}')
    try:
        bot.queue = await process_queue_requests(bot)
        await register_commands(bot)
        synced = await bot.tree.sync()
        print(f"📡 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)