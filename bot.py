import discord
from core import state
from discord.ext import commands
from dotenv import load_dotenv
import os
import logging
import asyncio
from config import settings
from commands.register import register_commands
from core.queue_manager import process_queue_requests

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

excluded_ids_raw = os.getenv("EXCLUDED_USER_IDS", "")
EXCLUDED_USER_IDS = set(int(uid.strip()) for uid in excluded_ids_raw.split(",") if uid.strip().isdigit())

bot = commands.Bot(command_prefix='/', intents=settings.INTENTS)

def is_excluded(user: discord.User | discord.Member) -> bool:
    return user.id in EXCLUDED_USER_IDS

def format_user(user: discord.User | discord.Member) -> str:
    return f"{user.display_name} ({user.name}#{user.discriminator})"

class DiscordHandler(logging.Handler):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.log_channel_id = LOG_CHANNEL_ID

    def emit(self, record):
        log_entry = self.format(record)
        channel = self.bot.get_channel(self.log_channel_id)
        if channel:
            asyncio.run_coroutine_threadsafe(
                channel.send(f"```{log_entry}```", silent=True),
                self.bot.loop
            )

logger = logging.getLogger('bot')
logger.setLevel(logging.INFO)

discord_handler = DiscordHandler(bot)
discord_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(discord_handler)

file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

@bot.event
async def on_connect():
    logger.info("🔌 Connected to Discord")

@bot.event
async def on_disconnect():
    logger.warning("🔌 Disconnected from Discord")

@bot.event
async def on_resumed():
    logger.info("♻️ Connection resumed")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.exception(f"💥 Unhandled error in event '{event}'", exc_info=True)

@bot.event
async def on_ready():
    logger.info(f'✅ Bot {bot.user} successfully started')
    try:
        state.reset_playback_state()
        bot.queue = await process_queue_requests(bot)
        await register_commands(bot)
        synced = await bot.tree.sync()
        total = len(bot.tree.get_commands())
        logger.info(f"📡 Synced {len(synced)} slash commands")

        if len(synced) < total:
            logger.warning(f"⚠️ Only {len(synced)} out of {total} commands synced. Possible limit reached.")

        for guild in bot.guilds:
            me = guild.me
            if not me.guild_permissions.manage_messages:
                channel = guild.system_channel or discord.utils.get(guild.text_channels, position=0)
                if channel:
                    await channel.send("⚠️ У бота нет прав 'Управление сообщениями'. Это может вызвать накопление 'Сейчас играет' сообщений.")
                    logger.warning(f"⚠️ No 'Manage Messages' permission in guild {guild.name}")
    except Exception as e:
        logger.exception(f"❌ Error during startup: {e}", exc_info=True)

@bot.event
async def on_message(message):
    if message.author != bot.user and not is_excluded(message.author):
        user_info = format_user(message.author)
        logger.info(f"📩 {user_info} in #{message.channel} @ {message.guild}: {message.content}")
    await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    if not is_excluded(ctx.author):
        user_info = format_user(ctx.author)
        logger.info(f"⚙️ /{ctx.command} by {user_info} in #{ctx.channel} @ {ctx.guild} — Args: {ctx.args} Kwargs: {ctx.kwargs}")

@bot.event
async def on_command_error(ctx, error):
    if not is_excluded(ctx.author):
        user_info = format_user(ctx.author)
        logger.error(f"❌ Error in /{ctx.command} by {user_info}: {error}", exc_info=True)
    await ctx.send(f"Произошла ошибка: {error}")

@bot.event
async def on_voice_state_update(member, before, after):
    if is_excluded(member):
        return

    user_info = format_user(member)
    if member.id == bot.user.id and before.channel and not after.channel:
        msg_to_delete = state.last_now_playing_message
        state.reset_playback_state()
        if msg_to_delete:
            try:
                await msg_to_delete.delete()
                logger.info(f"🗑️ Deleted 'Now Playing' message after disconnect")
            except (discord.NotFound, discord.HTTPException):
                pass
    elif before.channel != after.channel:
        if after.channel:
            logger.info(f"🔊 {user_info} joined VC: {after.channel.name}")
        if before.channel:
            logger.info(f"🔇 {user_info} left VC: {before.channel.name}")

@bot.event
async def on_member_join(member):
    if not is_excluded(member):
        logger.info(f"👤 {format_user(member)} joined {member.guild.name}")

@bot.event
async def on_member_remove(member):
    if not is_excluded(member):
        logger.info(f"🚪 {format_user(member)} left {member.guild.name}")

@bot.event
async def on_message_edit(before, after):
    if not is_excluded(before.author):
        logger.info(
            f"✏️ {format_user(before.author)} edited in #{before.channel}:\n"
            f"Before: {before.content}\nAfter:  {after.content}"
        )

@bot.event
async def on_message_delete(message):
    if not is_excluded(message.author):
        logger.info(f"🗑️ Deleted message by {format_user(message.author)} in #{message.channel}: {message.content}")

@bot.event
async def on_reaction_add(reaction, user):
    if not is_excluded(user):
        logger.info(f"😊 {format_user(user)} added {reaction.emoji} in #{reaction.message.channel}")

@bot.event
async def on_reaction_remove(reaction, user):
    if not is_excluded(user):
        logger.info(f"😐 {format_user(user)} removed {reaction.emoji} in #{reaction.message.channel}")

@bot.event
async def on_guild_join(guild):
    logger.info(f"➕ Joined new guild: {guild.name}")

@bot.event
async def on_guild_remove(guild):
    logger.info(f"➖ Removed from guild: {guild.name}")

if __name__ == "__main__":
    bot.run(TOKEN)
