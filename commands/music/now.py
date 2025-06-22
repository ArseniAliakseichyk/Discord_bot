import discord
from discord import app_commands
from core import state
import time

def format_duration(seconds: float) -> str:
    if seconds < 0:
        return "00:00"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

@app_commands.command(name="now", description="Показать текущий трек")
async def now_playing(interaction: discord.Interaction):
    if not state.current:
        await interaction.response.send_message("❌ Сейчас ничего не играет.")
        return

    embed = discord.Embed(
        title="🎵 Сейчас играет",
        description=f"[{state.current['title']}]({state.current.get('web_url', 'https://youtube.com')})",
        color=discord.Color.green() if state.current.get('source') == 'local' else discord.Color.blue()
    )

    vc = interaction.guild.voice_client
    if vc:
        if state.looping:
            status = "🔁 Повтор"
        elif vc.is_paused():
            status = "⏸️ На паузе"
        elif vc.is_playing():
            status = "▶️ Воспроизведение"
        else:
            status = "❌ Не воспроизводится"
    else:
        status = "❌ Не в голосовом канале"

    embed.add_field(name="Статус", value=status, inline=True)

    thumbnail = state.current.get('thumbnail', 'https://i.imgur.com/zG0SXqW.png')
    embed.set_thumbnail(url=thumbnail)

    embed.add_field(name="Длительность", value=state.current.get('duration', 'N/A'), inline=True)
    embed.add_field(name="Источник", value="Локальный файл" if state.current.get('source') == 'local' else "YouTube", inline=True)

    duration_seconds = state.current.get('duration_seconds', 0)
    if duration_seconds > 0:
        if state.elapsed_at_pause is not None:
            elapsed = state.elapsed_at_pause
        else:
            elapsed = time.time() - state.current_start_time

        if elapsed > duration_seconds:
            elapsed = duration_seconds
        elif elapsed < 0:
            elapsed = 0

        elapsed_str = format_duration(elapsed)
        duration_str = state.current['duration']

        if ":" not in duration_str:
            duration_str = format_duration(duration_seconds)

        embed.add_field(
            name="Прогресс",
            value=f"{elapsed_str} / {duration_str}",
            inline=False
        )

    requested_by = state.current.get('requested_by_name', 'Неизвестно')
    avatar_url = state.current.get('requested_by_avatar', 'https://i.imgur.com/7R5eEBd.png')

    embed.set_footer(text=f"Добавлено: {requested_by}", icon_url=avatar_url)

    await interaction.response.send_message(embed=embed)