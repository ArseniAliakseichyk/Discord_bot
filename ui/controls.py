import discord
import time
from core import state

class ControlButtons(discord.ui.View):
    def __init__(self, text_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.text_channel = text_channel

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            state.elapsed_at_pause = time.time() - state.current_start_time
            await self.text_channel.send("⏸️ Музыка на паузе.")

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
            await self.text_channel.send("▶️ Музыка продолжена.")

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await self.text_channel.send(f"⏭️ Трек `{state.current['title']}` пропущен.")

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        state.queue.clear()
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

    @discord.ui.button(label="🔄 Повтор", style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        state.looping = not state.looping
        await self.text_channel.send(
            f"🔄 Режим повтора: {'ВКЛ' if state.looping else 'ВЫКЛ'}"
        )