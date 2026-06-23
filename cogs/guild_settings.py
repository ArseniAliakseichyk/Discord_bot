"""Per-guild settings: DJ role, command channel, default volume."""

from __future__ import annotations

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from utils.checks import guild_authorized


class GuildSettings(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    group = app_commands.Group(
        name="settings",
        description="Настройки сервера (нужны права «Управление сервером»)",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @group.command(name="show", description="Показать текущие настройки")
    @guild_authorized()
    async def show(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        settings = await self.bot.db.get_settings(interaction.guild.id)

        dj = (
            interaction.guild.get_role(settings.dj_role_id)
            if settings.dj_role_id
            else None
        )
        channel = (
            interaction.guild.get_channel(settings.command_channel_id)
            if settings.command_channel_id
            else None
        )
        volume = (
            settings.default_volume
            if settings.default_volume is not None
            else self.bot.settings.default_volume
        )

        embed = discord.Embed(title="⚙️ Настройки сервера", color=0x2B2D31)
        embed.add_field(
            name="DJ-роль",
            value=dj.mention if dj else "не задана (управление доступно всем)",
            inline=False,
        )
        embed.add_field(
            name="Канал команд",
            value=channel.mention if channel else "не задан (любой канал)",
            inline=False,
        )
        embed.add_field(name="Громкость по умолчанию", value=f"{volume}%", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="djrole", description="Задать или сбросить DJ-роль")
    @app_commands.describe(role="Роль для управления музыкой; пусто — сбросить")
    @guild_authorized()
    async def djrole(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        assert interaction.guild is not None
        await self.bot.db.update_settings(
            interaction.guild.id, dj_role_id=role.id if role else None
        )
        if role:
            await interaction.response.send_message(
                f"✅ DJ-роль установлена: {role.mention}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ DJ-роль сброшена — управление доступно всем.", ephemeral=True
            )

    @group.command(name="channel", description="Ограничить команды одним каналом")
    @app_commands.describe(channel="Канал для команд; пусто — снять ограничение")
    @guild_authorized()
    async def channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        assert interaction.guild is not None
        await self.bot.db.update_settings(
            interaction.guild.id,
            command_channel_id=channel.id if channel else None,
        )
        if channel:
            await interaction.response.send_message(
                f"✅ Команды теперь только в {channel.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ Ограничение по каналу снято.", ephemeral=True
            )

    @group.command(name="volume", description="Громкость по умолчанию (0..200)")
    @app_commands.describe(value="Громкость в процентах, 0..200")
    @guild_authorized()
    async def volume(
        self,
        interaction: discord.Interaction,
        value: app_commands.Range[int, 0, 200],
    ) -> None:
        assert interaction.guild is not None
        await self.bot.db.update_settings(interaction.guild.id, default_volume=value)
        player: wavelink.Player | None = interaction.guild.voice_client  # type: ignore[assignment]
        if player is not None:
            await player.set_volume(value)
        await interaction.response.send_message(
            f"🔊 Громкость по умолчанию: {value}%", ephemeral=True
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(GuildSettings(bot))
