"""Voice channel commands: join, jointo, leave."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.constants import EMBED_COLOR, MSG_BOT_NOT_CONNECTED, MSG_JOIN_VOICE_FIRST
from utils.checks import guild_authorized, has_dj
from utils.player import connect_and_configure, player_of

logger = logging.getLogger("bot.voice")


class Voice(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def _cleanup(self, guild_id: int) -> None:
        music = self.bot.get_cog("Music")
        if music is not None:
            await music.clear_now_message(guild_id)  # type: ignore[attr-defined]
        await self.bot.db.clear_session(guild_id)

    @app_commands.command(name="join", description="Подключить бота к вашему голосовому каналу")
    @guild_authorized()
    @has_dj()
    async def join(self, interaction: discord.Interaction) -> None:
        if (
            not isinstance(interaction.user, discord.Member)
            or interaction.user.voice is None
            or interaction.user.voice.channel is None
        ):
            await interaction.response.send_message(
                MSG_JOIN_VOICE_FIRST, ephemeral=True
            )
            return
        if player_of(interaction.guild) is not None:
            await interaction.response.send_message(
                "ℹ️ Бот уже в голосовом канале.", ephemeral=True
            )
            return
        channel = interaction.user.voice.channel
        await connect_and_configure(channel, self.bot)
        await interaction.response.send_message(f"🔊 Подключился к `{channel.name}`.")

    @app_commands.command(
        name="jointo", description="Подключить бота к указанному голосовому каналу"
    )
    @app_commands.describe(channel="Имя или ID голосового канала")
    @guild_authorized()
    @has_dj()
    async def jointo(self, interaction: discord.Interaction, channel: str) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:  # guild_authorized() already rejects DMs; keep mypy happy
            return

        target: discord.VoiceChannel | None
        if channel.strip().isdigit():
            target = discord.utils.get(guild.voice_channels, id=int(channel))
        else:
            target = discord.utils.get(guild.voice_channels, name=channel.strip())
        if target is None:
            await interaction.followup.send(
                f"❌ Голосовой канал `{channel}` не найден.", ephemeral=True
            )
            return

        player = player_of(guild)
        if player is not None:
            if player.channel.id == target.id:
                await interaction.followup.send(
                    f"ℹ️ Бот уже в канале `{target.name}`.", ephemeral=True
                )
                return
            await player.move_to(target)
        else:
            await connect_and_configure(target, self.bot)

        embed = discord.Embed(
            title="🔊 Подключение к голосовому каналу",
            description=f"Бот подключился к `{target.name}`.",
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"Выполнил: {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @jointo.autocomplete("channel")
    async def channel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        current = current.lower()
        return [
            app_commands.Choice(name=vc.name, value=str(vc.id))
            for vc in interaction.guild.voice_channels
            if current in vc.name.lower() or current == str(vc.id)
        ][:25]

    @app_commands.command(name="leave", description="Отключить бота от голосового канала")
    @guild_authorized()
    @has_dj()
    async def leave(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is None or interaction.guild is None:
            await interaction.response.send_message(
                MSG_BOT_NOT_CONNECTED, ephemeral=True
            )
            return
        await player.disconnect()
        await self._cleanup(interaction.guild.id)
        await interaction.response.send_message("👋 Отключился и очистил очередь.")


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Voice(bot))
