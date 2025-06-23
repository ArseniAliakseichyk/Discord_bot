import discord
from core import state
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
        for guild in bot.guilds:
            me = guild.me
            if not me.guild_permissions.manage_messages:
                channel = guild.system_channel or discord.utils.get(guild.text_channels, position=0)
                if channel:
                    await channel.send("⚠️ У бота нет прав 'Управление сообщениями'. Это может привести к накоплению сообщений 'Сейчас играет'.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id and before.channel and not after.channel:
        msg_to_delete = state.last_now_playing_message
        state.reset_playback_state()
        
        if msg_to_delete:
            try:
                await msg_to_delete.delete()
            except (discord.NotFound, discord.HTTPException):
                pass


if __name__ == "__main__":
    bot.run(TOKEN)