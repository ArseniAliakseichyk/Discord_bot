"""
Оптимизированный плеер с prefetch следующего трека.
"""
import discord
import asyncio
import os
import logging
import time
from core import state
from core.audio_manager import (
    prepare_track_for_playback,
    prefetch_track,
    create_audio_source,
    get_audio_url
)
from ui.controls import ControlButtons

logger = logging.getLogger(__name__)


class AudioPreparationError(Exception):
    pass


async def _prefetch_next_track():
    """Prefetch следующего трека в очереди"""
    async with state.queue_lock:
        if len(state.queue) > 0:
            next_track = state.queue[0]
            query = next_track.get('query', '')

            # Не prefetch локальные файлы
            if not os.path.exists(query):
                asyncio.create_task(prefetch_track(query))


async def play_next(vc, text_channel: discord.TextChannel):
    """Воспроизводит следующий трек из очереди"""

    if vc:
        state.last_text_channels[vc.guild.id] = text_channel

    async with state.queue_lock:
        if not vc or not vc.is_connected():
            state.reset_playback_state()
            if state.last_now_playing_message:
                try:
                    await state.last_now_playing_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                state.last_now_playing_message = None
            logger.info("Bot is not in a voice channel, stopping playback")
            return

        if state.queue:
            state.current = state.queue.pop(0)
            state.current_start_time = time.time()
            state.elapsed_at_pause = None

            title = state.current.get('title', 'Unknown')
            logger.info(f"Playing: {title}")

            try:
                # Подготовка аудио источника
                source = await prepare_track_for_playback(state.current)
            except Exception as e:
                logger.error(f"Error preparing audio: {e}", exc_info=True)
                await text_channel.send(f"⚠️ Ошибка воспроизведения: `{title}`")
                # Пробуем следующий трек
                asyncio.create_task(play_next(vc, text_channel))
                return

            # Останавливаем текущее воспроизведение если есть
            if vc.is_playing() or vc.is_paused():
                vc.stop()

            # Callback после завершения трека
            async def after_playing(error):
                if error:
                    logger.error(f"Playback error: {error}", exc_info=True)

                try:
                    if vc and vc.source:
                        vc.source.cleanup()
                except:
                    pass

                # Обработка loop режима
                if state.looping and state.current and not state.is_manual_operation:
                    async with state.queue_lock:
                        state.queue.insert(0, state.current)

                state.is_manual_operation = False
                await play_next(vc, text_channel)

            def after_playing_sync(error):
                asyncio.run_coroutine_threadsafe(after_playing(error), vc.loop)

            # Запуск воспроизведения
            vc.play(source, after=after_playing_sync)

            # Prefetch следующего трека (в фоне)
            asyncio.create_task(_prefetch_next_track())

            # Создание embed
            source_type = state.current.get('source', 'youtube')
            if source_type == 'local':
                color = discord.Color.green()
                source_text = "Локальный файл"
            elif source_type == 'spotify':
                color = discord.Color.gold()
                source_text = "Spotify"
            else:
                color = discord.Color.gold()
                source_text = "YouTube"

            embed = discord.Embed(
                title="🎵 Сейчас играет",
                description=f"[{state.current['title']}]({state.current.get('web_url', 'https://youtube.com')})",
                color=color
            )

            thumbnail = state.current.get('thumbnail', 'https://i.imgur.com/zG0SXqW.png')
            embed.set_thumbnail(url=thumbnail)

            embed.add_field(name="Длительность", value=state.current.get('duration', 'N/A'), inline=True)
            embed.add_field(name="Источник", value=source_text, inline=True)
            embed.add_field(name="Статус", value="🔁 Повтор" if state.looping else "▶️ Воспроизведение", inline=True)

            # В очереди
            queue_len = len(state.queue)
            if queue_len > 0:
                embed.add_field(name="В очереди", value=f"{queue_len} трек(ов)", inline=True)

            requested_by = state.current.get('requested_by_name', 'Неизвестно')
            avatar_url = state.current.get('requested_by_avatar', 'https://i.imgur.com/7R5eEBd.png')
            embed.set_footer(text=f"Добавлено: {requested_by}", icon_url=avatar_url)

            # Удаляем старое сообщение
            if state.last_now_playing_message:
                try:
                    await state.last_now_playing_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                state.last_now_playing_message = None

            # Отправляем новое
            state.last_now_playing_message = await text_channel.send(
                embed=embed,
                view=ControlButtons(text_channel, play_next)
            )

            logger.info(f"Started playback: {title}")

        else:
            # Очередь пуста
            msg_to_delete = state.last_now_playing_message
            state.reset_playback_state()

            if vc and vc.guild:
                state.idle_since[vc.guild.id] = time.time()

            if msg_to_delete:
                try:
                    await msg_to_delete.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

            logger.info("Queue is empty, stopping playback")
