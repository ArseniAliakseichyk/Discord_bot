import discord
from discord import app_commands
from config import settings

@app_commands.command(name="announce", description="Создать официальное объявление")
@app_commands.describe(
    message="Текст объявления",
    channel="Канал для отправки (по умолчанию текущий)",
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
    
    target_channel = channel or interaction.channel
    mention = mention_role.mention if mention_role else ""
    
    try:
        embed = discord.Embed(
            title="📢 Официальное объявление",
            description=f"{mention}\n{message}",
            color=0x2b2d31
        )
        embed.set_footer(text=f"От {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
        
        await target_channel.send(embed=embed)
        await interaction.followup.send("✅ Объявление успешно опубликовано!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)