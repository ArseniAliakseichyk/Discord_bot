import discord
from discord import ui
from core import state
import time
import asyncio

class ControlButtons(discord.ui.View):
    def __init__(self, text_channel: discord.TextChannel, play_next_func):
        super().__init__(timeout=None)
        self.text_channel = text_channel
        self.play_next = play_next_func

        vc = text_channel.guild.voice_client
        is_playing = vc and vc.is_playing()
        has_next = len(state.queue) > 0 or state.looping
        is_looping = state.looping

        for item in self.children:
            if item.label == "⏸️ Пауза":
                item.disabled = not is_playing
            elif item.label == "▶️ Продолжить":
                item.disabled = is_playing or not (vc and vc.is_paused())
            elif item.label == "⏭️ Скип":
                item.disabled = not has_next
            elif item.label == "🔄 Повтор":
                item.style = discord.ButtonStyle.success if is_looping else discord.ButtonStyle.secondary

    async def update_embed(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not state.current:
            return

        status = "▶️ Воспроизведение"
        if vc.is_paused():
            status = "⏸️ На паузе"
        elif state.looping:
            status = "🔁 Повтор"

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

        embed.add_field(
            name="Длительность",
            value=state.current.get('duration', 'N/A'),
            inline=True
        )

        embed.add_field(
            name="Источник",
            value=source_text,
            inline=True
        )
        
        embed.add_field(
            name="Статус", 
            value=status,
            inline=True
        )
        
        requested_by = state.current.get('requested_by_name', 'Неизвестно')
        avatar_url = state.current.get('requested_by_avatar', 'https://i.imgur.com/7R5eEBd.png')
        
        embed.set_footer(
            text=f"Добавлено: {requested_by}",
            icon_url=avatar_url
        )

        new_view = ControlButtons(self.text_channel, self.play_next)
        await state.last_now_playing_message.edit(embed=embed, view=new_view)

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            state.elapsed_at_pause = time.time() - state.current_start_time
            await self.update_embed(interaction)

    @discord.ui.button(label="▶️ Продолжить", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            if state.elapsed_at_pause is not None:
                state.current_start_time = time.time() - state.elapsed_at_pause
                state.elapsed_at_pause = None
            await self.update_embed(interaction)

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        state.queue.clear()
        state.pending_queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            if state.last_now_playing_message:
                try:
                    await state.last_now_playing_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                state.last_now_playing_message = None
            await self.text_channel.send("⏹️ Воспроизведение остановлено и очередь очищена.")