"""The /help command (lists available commands)."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from utils.checks import guild_authorized


class Help(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Показать список команд")
    @guild_authorized()
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🎵 Доступные команды", color=0x2B2D31)
        embed.add_field(
            name="🎶 Музыка",
            value=(
                "**/play** — добавить трек или плейлист\n"
                "**/search** — найти и выбрать из списка\n"
                "**/now** — текущий трек\n"
                "**/queue** — очередь\n"
                "**/shuffle** — перемешать очередь\n"
                "**/clear** — очистить очередь\n"
                "**/skip** — пропустить трек\n"
                "**/pause**, **/resume**, **/stop**\n"
                "**/autoplay** — радио из похожих треков"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔊 Голос",
            value=(
                "**/join** — зайти в ваш голосовой канал\n"
                "**/jointo** — зайти в конкретный канал\n"
                "**/leave** — выйти из канала"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Утилиты",
            value=(
                "**/announce** — быстрый анонс\n"
                "**/constructor** — конструктор эмбедов\n"
                "**/settings** — настройки сервера"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Help(bot))
