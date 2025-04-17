import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
import random
import urllib.parse

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

MUSIC_FOLDER = './music'
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='//', intents=intents)
tree = bot.tree

queue = []
looping = False
current = None


@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user.name}')
    try:
        synced = await tree.sync()
        print(f"📡 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")


async def fetch_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return await asyncio.to_thread(ydl.extract_info, query, download=False)


async def play_next(vc):
    global current
    if looping and current:
        queue.insert(0, current)

    if queue:
        current = queue.pop(0)
        query = current['query']

        try:
            if os.path.exists(query):
                source = discord.FFmpegPCMAudio(query)
            else:
                info = await fetch_info(query)
                if 'entries' in info:
                    audio_url = info['entries'][0]['url']
                else:
                    audio_url = info['url']
                source = discord.FFmpegPCMAudio(audio_url)
        except Exception as e:
            print(f"Ошибка при получении аудио: {e}")
            await play_next(vc)
            return

        source = discord.PCMVolumeTransformer(source, volume=0.5)

        def after_playing(error):
            future = asyncio.run_coroutine_threadsafe(play_next(vc), bot.loop)
            try:
                future.result()
            except Exception as e:
                print(f"Error in after_playing: {e}")

        vc.play(source, after=after_playing)
        await vc.channel.send(f"▶️ Сейчас играет: `{current['title']}`", view=ControlButtons())
    else:
        current = None


class ControlButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Музыка на паузе.", ephemeral=True)

    @discord.ui.button(label="▶️ Продолжить", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Продолжено.", ephemeral=True)

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Трек пропущен.", ephemeral=True)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await interaction.response.send_message("⏹️ Музыка остановлена и очередь очищена.", ephemeral=True)

    @discord.ui.button(label="🔁 Повтор", style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        global looping
        looping = not looping
        await interaction.response.send_message(f"🔁 Режим повтора: {'ВКЛ' if looping else 'ВЫКЛ'}", ephemeral=True)


@tree.command(name="play", description="Проиграть музыку с YouTube или локального файла")
@app_commands.describe(query="Ссылка на YouTube или имя локального файла")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    vc = interaction.guild.voice_client
    if not vc:
        if interaction.user.voice:
            vc = await interaction.user.voice.channel.connect()
        else:
            await interaction.followup.send("❌ Сначала подключитесь к голосовому каналу.")
            return

    query = query.strip()
    local_path = os.path.join(MUSIC_FOLDER, query)

    if os.path.exists(local_path):
        track = {'query': local_path, 'title': query}
        queue.append(track)
        await interaction.followup.send(f"📥 Добавлен в очередь: `{query}`")
    else:
        try:
            info = await fetch_info(query)
            if 'entries' in info:
                await interaction.followup.send(f"📥 Добавлено треков из плейлиста: {len(info['entries'])}")
                for entry in info['entries']:
                    queue.append({'query': entry['webpage_url'], 'title': entry['title']})
            else:
                track = {'query': query, 'title': info['title']}
                queue.append(track)
                await interaction.followup.send(f"📥 Добавлен в очередь: `{info['title']}`")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {str(e)}")
            return

    if not vc.is_playing() and not vc.is_paused():
        await play_next(vc)


@tree.command(name="now", description="Показать текущий трек")
async def now_playing(interaction: discord.Interaction):
    if current:
        await interaction.response.send_message(f"🎵 Сейчас играет: `{current['title']}`")
    else:
        await interaction.response.send_message("❌ Сейчас ничего не играет.")


@tree.command(name="queue", description="Показать очередь")
async def show_queue(interaction: discord.Interaction):
    if queue:
        msg = "\n".join([f"{i+1}. {track['title']}" for i, track in enumerate(queue)])
        await interaction.response.send_message(f"📜 Очередь:\n{msg}")
    else:
        await interaction.response.send_message("🚫 Очередь пуста.")


@tree.command(name="shuffle", description="Перемешать очередь")
async def shuffle_queue(interaction: discord.Interaction):
    if queue:
        random.shuffle(queue)
        await interaction.response.send_message("🔀 Очередь перемешана.")
    else:
        await interaction.response.send_message("🚫 Очередь пуста.")


@tree.command(name="clear", description="Очистить очередь")
async def clear_queue(interaction: discord.Interaction):
    queue.clear()
    await interaction.response.send_message("🧹 Очередь очищена.")


@tree.command(name="join", description="Подключить бота к голосовому каналу")
async def join(interaction: discord.Interaction):
    if interaction.user.voice:
        await interaction.user.voice.channel.connect()
        await interaction.response.send_message(f"🔊 Подключился к `{interaction.user.voice.channel.name}`")
    else:
        await interaction.response.send_message("❌ Вы не в голосовом канале.")


@tree.command(name="leave", description="Отключить бота от голосового канала")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        queue.clear()
        await interaction.response.send_message("👋 Отключился и очистил очередь.")
    else:
        await interaction.response.send_message("❌ Бот не в голосовом канале.")


bot.run(TOKEN)