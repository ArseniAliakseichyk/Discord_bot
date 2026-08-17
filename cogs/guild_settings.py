"""Per-guild settings: DJ role, command channel, default volume."""

from __future__ import annotations

import logging

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from ui.v2 import PanelView, make_panel
from utils.checks import guild_authorized
from utils.player import player_of, resolve_volume

logger = logging.getLogger("bot.settings")


class GuildSettingsCog(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    group = app_commands.Group(
        name="settings",
        description="Настройки сервера (нужны права «Управление сервером»)",
        guild_only=True,
        # A UI default only — server admins can re-open the command to anyone,
        # so every subcommand also carries a runtime permission check.
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @group.command(name="show", description="Показать текущие настройки")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
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
        volume = resolve_volume(settings, self.bot.settings)

        body = "\n".join(
            (
                f"**DJ-роль:** {dj.mention if dj else 'не задана (управление доступно всем)'}",
                f"**Канал команд:** {channel.mention if channel else 'не задан (любой канал)'}",
                f"**Громкость по умолчанию:** {volume}%",
                "",
                "-# Тикеты настраиваются в `/ticket config`, "
                "журнал модерации — в `/mod log`.",
            )
        )
        view = PanelView(timeout=None)
        view.add_item(make_panel(title="⚙️ Настройки сервера", body=body))
        await interaction.response.send_message(view=view, ephemeral=True)

    @group.command(name="djrole", description="Задать или сбросить DJ-роль")
    @app_commands.describe(role="Роль для управления музыкой; пусто — сбросить")
    @guild_authorized()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def djrole(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        if interaction.guild is None:
            return
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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            return
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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def volume(
        self,
        interaction: discord.Interaction,
        value: app_commands.Range[int, 0, 200],
    ) -> None:
        if interaction.guild is None:
            return
        await self.bot.db.update_settings(interaction.guild.id, default_volume=value)
        player = player_of(interaction.guild)
        if player is not None:
            try:
                await player.set_volume(value)
            except (wavelink.LavalinkException, wavelink.NodeException):
                logger.warning("Could not apply volume to the live player", exc_info=True)
        await interaction.response.send_message(
            f"🔊 Громкость по умолчанию: {value}%", ephemeral=True
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(GuildSettingsCog(bot))
