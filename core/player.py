import discord
import asyncio
import os
import random
from core import state
from utils.yt_utils import fetch_info
from ui.controls import ControlButtons

async def play_next(vc, text_channel: discord.TextChannel):
    if state.looping and state.current:
        state.queue.insert(0, state.current)

    if state.queue:
        state.current = state.queue.pop(0)
        query = state.current['query']

        try:
            if os.path.exists(query):
                source = discord.FFmpegPCMAudio(
                    executable="ffmpeg",
                    source=query,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn -b:a 128k"
                )
            else:
                info = await fetch_info(query)
                audio_url = info['url'] if not 'entries' in info else info['entries'][0]['url']
                source = discord.FFmpegPCMAudio(
                    executable="ffmpeg",
                    source=audio_url,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn -b:a 128k"
                )
        except Exception as e:
            print(f"Ошибка: {e}")
            await text_channel.send(f"⚠️ Ошибка воспроизведения: {str(e)}")
            await play_next(vc, text_channel)
            return

        source = discord.PCMVolumeTransformer(source, volume=0.5)

        def after_playing(error):
            if error:
                print(f"Ошибка воспроизведения: {error}")
            future = asyncio.run_coroutine_threadsafe(play_next(vc, text_channel), vc.loop)
            try: 
                future.result()
            except Exception as e:
                print(f"Ошибка в after_playing: {e}")

        vc.play(source, after=after_playing)
        await text_channel.send(
            f"▶️ Сейчас играет: `{state.current['title']}`",
            view=ControlButtons(text_channel)
        )
    else:
        state.current = None