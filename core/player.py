import discord
import asyncio
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from core import state
from utils.yt_utils import fetch_info_sync
from ui.controls import ControlButtons

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=2)

def prepare_audio(query, is_local):
    logger.info(f"Preparing audio: {query}")
    try:
        if is_local:
            return discord.FFmpegPCMAudio(
                executable="ffmpeg",
                source=query,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn -b:a 128k"
            )
        else:
            if 'playlist?list=' in query:
                raise ValueError("Playlist URL should not be used directly")
                
            info = fetch_info_sync(query)
            if not info:
                raise ValueError("Failed to fetch audio info")
                
            audio_url = info.get('url')
            if not audio_url:
                raise ValueError("No audio URL in response")
                
            logger.info(f"Using audio URL: {audio_url[:50]}...")
            return discord.FFmpegPCMAudio(
                executable="ffmpeg",
                source=audio_url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn -b:a 128k"
            )
    except Exception as e:
        logger.error(f"Full preparation error: {str(e)}")
        raise AudioPreparationError(f"Ошибка подготовки аудио: {str(e)}")

class AudioPreparationError(Exception):
    pass

async def play_next(vc, text_channel: discord.TextChannel):
    if state.looping and state.current:
        state.queue.insert(0, state.current)
        logger.info(f"Looping enabled, re-inserted current track: {state.current['title']}")

    if state.queue:
        state.current = state.queue.pop(0)
        query = state.current['query']
        is_local = os.path.exists(query)
        logger.info(f"Playing next track: {state.current['title']} (query: {query})")

        try:
            loop = asyncio.get_running_loop()
            source = await loop.run_in_executor(executor, prepare_audio, query, is_local)
        except Exception as e:
            logger.error(f"Error preparing audio: {str(e)}", exc_info=True)
            await text_channel.send(f"⚠️ Ошибка воспроизведения: {str(e)}")
            await play_next(vc, text_channel)
            return

        source = discord.PCMVolumeTransformer(source, volume=0.5)

        def after_playing(error):
            if error:
                logger.error(f"Playback error: {error}", exc_info=True)
            if vc and vc.source:
                vc.source.cleanup()
            future = asyncio.run_coroutine_threadsafe(play_next(vc, text_channel), vc.loop)
            try:
                future.result()
            except Exception as e:
                logger.error(f"Error in after_playing: {e}", exc_info=True)

        vc.play(source, after=after_playing)
        await text_channel.send(
            f"▶️ Сейчас играет: `{state.current['title']}`",
            view=ControlButtons(text_channel)
        )
        logger.info(f"Started playback for: {state.current['title']}")
    else:
        state.current = None
        logger.info("Queue is empty, stopping playback")