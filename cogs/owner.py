"""Owner commands for managing private-bot authorization."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from ui.v2 import PanelView, make_panel
from utils.checks import is_owner

logger = logging.getLogger("bot.owner")


def _parse_guild_id(raw: str | None, interaction: discord.Interaction) -> int | None:
    if raw and raw.strip().isdigit():
        return int(raw.strip())
    if interaction.guild is not None:
        return interaction.guild.id
    return None


class Owner(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @app_commands.command(name="authorize", description="Авторизовать сервер (владелец)")
    @app_commands.describe(guild_id="ID сервера; по умолчанию — текущий")
    @is_owner()
    async def authorize(
        self, interaction: discord.Interaction, guild_id: str | None = None
    ) -> None:
        gid = _parse_guild_id(guild_id, interaction)
        if gid is None:
            await interaction.response.send_message(
                "❌ Укажите ID сервера.", ephemeral=True
            )
            return
        added = await self.bot.db.authorize_guild(gid, interaction.user.id)
        if added:
            logger.info("Guild %s authorized by %s", gid, interaction.user.id)
            await interaction.response.send_message(
                f"✅ Сервер `{gid}` авторизован.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ Сервер `{gid}` уже был авторизован.", ephemeral=True
            )

    @app_commands.command(
        name="deauthorize", description="Снять авторизацию сервера (владелец)"
    )
    @app_commands.describe(guild_id="ID сервера; по умолчанию — текущий")
    @is_owner()
    async def deauthorize(
        self, interaction: discord.Interaction, guild_id: str | None = None
    ) -> None:
        gid = _parse_guild_id(guild_id, interaction)
        if gid is None:
            await interaction.response.send_message(
                "❌ Укажите ID сервера.", ephemeral=True
            )
            return
        removed = await self.bot.db.deauthorize_guild(gid)
        if not removed:
            await interaction.response.send_message(
                f"ℹ️ Сервер `{gid}` не был авторизован.", ephemeral=True
            )
            return

        logger.info("Guild %s deauthorized by %s", gid, interaction.user.id)
        message = f"✅ Авторизация сервера `{gid}` снята."
        guild = self.bot.get_guild(gid)
        if guild is not None:
            try:
                await guild.leave()
            except discord.HTTPException:
                logger.exception("Failed to leave guild %s", gid)
                message += " Не удалось выйти из сервера — сделайте это вручную."
            else:
                message += " Бот вышел из сервера."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="servers", description="Список серверов бота и их статус (владелец)"
    )
    @is_owner()
    async def servers(self, interaction: discord.Interaction) -> None:
        authorized = await self.bot.db.authorized_guilds()
        if not self.bot.guilds:
            body = "Бот не состоит ни в одном сервере."
        else:
            body = "\n".join(
                f"{'✅' if g.id in authorized else '⛔'} **{g.name}** "
                f"(`{g.id}`) — {g.member_count} участников"
                for g in self.bot.guilds
            )
        extra = authorized - {g.id for g in self.bot.guilds}
        if extra:
            body += "\n\n**Авторизованы, но бот не в сервере**\n" + ", ".join(
                f"`{gid}`" for gid in extra
            )
        view = PanelView(timeout=None)
        view.add_item(make_panel(title="🖥️ Серверы бота", body=body))
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Owner(bot))
