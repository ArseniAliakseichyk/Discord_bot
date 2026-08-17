"""The /constructor command.

Thin by design: everything the builder does lives in the ``ui.builder`` package
(state, modals, field pickers, image handling, button rows, panel).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from ui.builder import GigaBuilderView
from ui.v2 import send_panel
from utils.checks import can_announce


class Builder(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="constructor", description="Интерактивный конструктор анонсов"
    )
    @app_commands.describe(
        channel="Канал для публикации",
        mention_role="Роль для упоминания при публикации",
    )
    @can_announce()
    async def constructor(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        mention_role: discord.Role | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is not None and not channel.permissions_for(guild.me).send_messages:
            await interaction.response.send_message(
                f"❌ У бота нет прав писать в {channel.mention} — "
                "выберите другой канал.",
                ephemeral=True,
            )
            return
        view = GigaBuilderView(interaction.user, channel, mention_role, self.bot)
        await send_panel(interaction, view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Builder(bot))
