import discord
import time
from core import state

class ControlButtons(discord.ui.View):
    def __init__(self, text_channel: discord.TextChannel, is_playing: bool, has_next: bool, is_looping: bool):
        super().__init__(timeout=None)
        self.text_channel = text_channel

        for item in self.children:
            if item.label == "⏸️ Пауза":
                item.disabled = not is_playing
            elif item.label == "▶️ Продолжить":
                item.disabled = is_playing or not state.current
            elif item.label == "⏭️ Скип":
                item.disabled = not has_next
            elif item.label == "🔄 Повтор":
                item.style = discord.ButtonStyle.success if is_looping else discord.ButtonStyle.secondary

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.is_manual_operation = True
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            state.elapsed_at_pause = time.time() - state.current_start_time

            is_playing = False
            has_next = len(state.queue) > 0
            is_looping = state.looping
            new_view = ControlButtons(self.text_channel, is_playing, has_next, is_looping)
            await state.last_now_playing_message.edit(view=new_view)

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

            is_playing = True
            has_next = len(state.queue) > 0
            is_looping = state.looping
            new_view = ControlButtons(self.text_channel, is_playing, has_next, is_looping)
            await state.last_now_playing_message.edit(view=new_view)

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

        is_playing = interaction.guild.voice_client.is_playing() if interaction.guild.voice_client else False
        has_next = len(state.queue) > 0
        is_looping = state.looping
        new_view = ControlButtons(self.text_channel, is_playing, has_next, is_looping)
        await state.last_now_playing_message.edit(view=new_view)