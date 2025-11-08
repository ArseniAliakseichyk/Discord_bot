import discord
from discord import app_commands
from discord.ext import commands
import config.settings as config

from .views import PersistentButtonsView, TicketManagementView

from .embeds import get_rules_embed

class RoleButtonCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(PersistentButtonsView(self.bot))
        self.bot.add_view(TicketManagementView())
        print("Персистентные View (кнопки) успешно зарегистрированы.")

    @app_commands.command( 
        name="send_rules",
        description="Отправить сообщение с правилами и кнопками."
    )
    async def send_rules_message(self, interaction: discord.Interaction): 
        
        allowed_roles_ids = config.ANNOUNCE.get("ALLOWED_ROLES", [])
        
        user_roles_ids = [role.id for role in interaction.user.roles]
        has_permission = any(role_id in allowed_roles_ids for role_id in user_roles_ids)

        if not has_permission:
            await interaction.response.send_message(
                "❌ **Доступ закрыт!** У вас нет необходимой роли для использования этой команды.",
                ephemeral=True
            )
            return
        
        try:
            embed = await get_rules_embed(self.bot)
        except Exception as e:
            print(f"Ошибка при получении Embed правил: {e}")
            await interaction.response.send_message(
                f"❌ Ошибка при создании Embed правил: `{e}`. Проверьте ID в .env.", 
                ephemeral=True
            )
            return

        await interaction.response.send_message("✅ Сообщение с правилами отправлено в канал.", ephemeral=True)
        
        await interaction.channel.send(embed=embed, view=PersistentButtonsView(self.bot))

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleButtonCog(bot))