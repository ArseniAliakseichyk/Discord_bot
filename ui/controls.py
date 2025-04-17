import discord
from core import state

class ControlButtons(discord.ui.View):
    def __init__(self, text_channel: discord.TextChannel):
        super().__init__(timeout=None)
        self.text_channel = text_channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await self.text_channel.send("⏸️ Музыка на паузе.")

    @discord.ui.button(label="▶️ Продолжить", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await self.text_channel.send("▶️ Музыка продолжена.")

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await self.text_channel.send("⏭️ Трек пропущен.")

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await self.text_channel.send("⏹️ Воспроизведение остановлено и очередь очищена.")

    @discord.ui.button(label="🔄 Повтор", style=discord.ButtonStyle.secondary)
    async def loop_(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state.looping = not state.looping
        await self.text_channel.send(
            f"🔄 Режим повтора: {'ВКЛ' if state.looping else 'ВЫКЛ'}"
        )