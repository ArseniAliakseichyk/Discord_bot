import discord
from discord import app_commands
from config import settings
import os

@app_commands.command(name="announce", description="Создать официальное объявление")
@app_commands.describe(
    message="Текст объявления",
    channel="Канал для отправки (по умолчанию официальный)",
    mention_role="Роль для упоминания (ID или название)"
)
async def announce(
    interaction: discord.Interaction,
    message: str,
    channel: discord.TextChannel = None,
    mention_role: str = None
):
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
        announce_config = settings.ANNOUNCE
        default_channel_id = announce_config["DEFAULT_CHANNEL"]
        target_channel = channel or interaction.guild.get_channel(default_channel_id)
        
        if not target_channel:
            return await interaction.followup.send("❌ Официальный канал не настроен!", ephemeral=True)

        role = None
        if mention_role:
            try:
                role = interaction.guild.get_role(int(mention_role))
            except ValueError:
                role = discord.utils.get(interaction.guild.roles, name=mention_role)
            
            if not role:
                return await interaction.followup.send("❌ Роль не найдена!", ephemeral=True)

        embed = discord.Embed(
            title="📢 Официальное объявление",
            description=f"{role.mention if role else ''}\n{message}",
            color=announce_config["COLOR"]
        )
        embed.set_footer(
            text=f"От {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )
        
        await target_channel.send(embed=embed)
        await interaction.followup.send("✅ Объявление успешно опубликовано!", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)

@announce.autocomplete("mention_role")
async def role_autocomplete(interaction: discord.Interaction, current: str):
    try:
        allowed_roles = settings.ANNOUNCE["ALLOWED_ROLES"]
        return [
            app_commands.Choice(name=f"{role.name} (ID: {role.id})", value=str(role.id))
            for role in interaction.guild.roles
            if role.id in allowed_roles and current.lower() in role.name.lower()
        ][:25]
    except:
        return []