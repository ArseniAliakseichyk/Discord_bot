import discord
from discord import app_commands
from config import settings

@app_commands.command(name="announce", description="Создать официальное объявление")
@app_commands.describe(
    message="Текст объявления",
    channel="Канал для отправки (по умолчанию официальный)",
    mention_role="Роль для упоминания"
)
@app_commands.checks.has_permissions(administrator=True)
async def announce(
    interaction: discord.Interaction,
    message: str,
    channel: discord.TextChannel = None,
    mention_role: discord.Role = None
):
    await interaction.response.defer(ephemeral=True)
    
    announce_config = settings.ANNOUNCE
    default_channel_id = announce_config["DEFAULT_CHANNEL"]
    
    target_channel = channel or interaction.guild.get_channel(default_channel_id)
    if not target_channel:
        await interaction.followup.send("❌ Официальный канал не настроен!", ephemeral=True)
        return

    mention = mention_role.mention if mention_role else ""
    
    try:
        embed = discord.Embed(
            title="📢 Официальное объявление",
            description=f"{mention}\n{message}",
            color=announce_config["COLOR"]
        )
        embed.set_footer(
            text=f"От {interaction.user.display_name}", 
            icon_url=interaction.user.avatar.url
        )
        
        await target_channel.send(embed=embed)
        await interaction.followup.send(
            "✅ Объявление успешно опубликовано!", 
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Ошибка: {str(e)}", 
            ephemeral=True
        )

@announce.autocomplete("mention_role")
async def role_autocomplete(
    interaction: discord.Interaction, 
    current: str
):
    allowed_roles = settings.ANNOUNCE["ALLOWED_ROLES"]
    return [
        app_commands.Choice(name=role.name, value=role.id)
        for role in interaction.guild.roles
        if role.id in allowed_roles and current.lower() in role.name.lower()
    ][:25]

@announce.before_invoke
async def check_permissions(interaction: discord.Interaction):
    user_roles = [role.id for role in interaction.user.roles]
    allowed_roles = settings.ANNOUNCE["ALLOWED_ROLES"]
    
    if not any(role_id in allowed_roles for role_id in user_roles):
        raise app_commands.MissingPermissionsError(["announce"])