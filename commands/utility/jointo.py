import discord
from discord import app_commands
from core.voice import connect_to_voice
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@app_commands.command(name="jointo", description="Подключить бота к указанному голосовому каналу")
@app_commands.describe(channel="Имя или ID голосового канала")
async def jointo(interaction: discord.Interaction, channel: str):
    allowed_roles = list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else []
    user_roles = [role.id for role in interaction.user.roles]
    common_roles = set(allowed_roles) & set(user_roles)
    
    if not interaction.user.guild_permissions.administrator:
        if not common_roles:
            await interaction.response.send_message(
                "❌ Требуется одна из разрешенных ролей или права администратора!",
                ephemeral=True
            )
            return

    await interaction.response.defer(ephemeral=True)
    
    try:
        target_channel = None
        if channel.strip().isdigit():
            target_channel = discord.utils.get(interaction.guild.voice_channels, id=int(channel))
        else:
            target_channel = discord.utils.get(interaction.guild.voice_channels, name=channel.strip())
        
        if not target_channel:
            return await interaction.followup.send(f"❌ Голосовой канал `{channel}` не найден!", ephemeral=True)

        vc = interaction.guild.voice_client
        if vc:
            if vc.channel.id == target_channel.id:
                return await interaction.followup.send(
                    f"❌ Бот уже подключен к каналу `{target_channel.name}`!",
                    ephemeral=True
                )
            await vc.disconnect()

        vc = await connect_to_voice(interaction, channel=target_channel)
        if vc:
            embed = discord.Embed(
                title="🔊 Подключение к голосовому каналу",
                description=f"Бот успешно подключился к каналу `{target_channel.name}`",
                color=0x2b2d31
            )
            embed.set_footer(
                text=f"Команда выполнена: {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            return await interaction.followup.send(
                f"❌ Не удалось подключиться к каналу `{target_channel.name}`!",
                ephemeral=True
            )

    except Exception as e:
        logger.error(f"Error in jointo command: {str(e)}")
        await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)

@jointo.autocomplete("channel")
async def channel_autocomplete(interaction: discord.Interaction, current: str):
    try:
        return [
            app_commands.Choice(
                name=channel.name,
                value=str(channel.id)
            )
            for channel in interaction.guild.voice_channels
            if current.lower() in channel.name.lower() or current == str(channel.id)
        ][:25]
    except Exception as e:
        logger.error(f"Error in channel autocomplete: {str(e)}")
        return []