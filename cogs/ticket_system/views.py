import discord
from discord.ui import Button, View, Modal, TextInput
from discord.ext import commands
import config.settings as config

from .helpers import (
    get_next_ticket_number, 
    get_ticket_channel_name,
    send_initial_ticket_message,
    claim_ticket_logic
)

from commands.utility.help import help_command

class TicketModal(Modal, title="Опишите ваш запрос в поддержку"):
    """Модальное окно для сбора информации о запросе в поддержку."""
    
    subject = TextInput(
        label="Тема запроса (в 1-2 слова)",
        placeholder="Например: Проблема с ролью, Вопрос по ивенту...",
        max_length=50,
        required=True
    )
    
    description = TextInput(
        label="Подробное описание проблемы",
        placeholder="Опишите проблему, предоставьте ссылки (если возможно).",
        style=discord.TextStyle.long,
        max_length=1000,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        guild = interaction.guild
        user = interaction.user
        
        ticket_subject = self.subject.value
        ticket_description = self.description.value
        
        if not config.TICKET_CATEGORY_ID or not config.SUPPORT_ROLE_ID:
            await interaction.followup.send("❌ Настройка системы тикетов не завершена.", ephemeral=True)
            return

        category = guild.get_channel(config.TICKET_CATEGORY_ID)
        if not category:
            await interaction.followup.send("❌ Не удалось найти категорию для тикетов.", ephemeral=True)
            return
            
        ticket_number = get_next_ticket_number()
        channel_name = get_ticket_channel_name(user.name, ticket_number, ticket_subject)
        
        try:
            support_role = guild.get_role(config.SUPPORT_ROLE_ID)
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            }
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)

            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            
            await send_initial_ticket_message(ticket_channel, user, ticket_subject, ticket_description)
            
            await interaction.followup.send(
                f"✅ Ваш запрос отправлен! "
                f"Ожидайте, пока администрация возьмет его в работу. "
                f"Внимание: Вы **не** увидите этот канал, пока его не откроет сотрудник поддержки.",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(f"❌ Произошла ошибка при создании тикета: {e}", ephemeral=True)
            print(f"Ошибка создания тикета: {e}")

class TicketManagementView(View):
    """Персистентный View для управления тикетом (взять в работу, закрыть)."""
    
    def __init__(self, is_claimed=False, timeout=None):
        super().__init__(timeout=timeout)
        self.is_claimed = is_claimed
        
        if is_claimed:
            for item in self.children:
                if item.custom_id == "claim_ticket":
                    self.remove_item(item)
    
    @discord.ui.button(label="Взять в работу", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await claim_ticket_logic(interaction, interaction.message)
    
    @discord.ui.button(label="Закрыть тикет", style=discord.ButtonStyle.primary, custom_id="close_ticket")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        member = interaction.user
        
        is_support = member.guild.get_role(config.SUPPORT_ROLE_ID) and member in member.guild.get_role(config.SUPPORT_ROLE_ID).members
        is_admin = member.guild_permissions.administrator
        
        if not (is_support or is_admin):
            await interaction.response.send_message("❌ Только администратор или саппорт могут закрыть тикет.", ephemeral=True)
            return

        creator_id = None
        creator = None
        topic = interaction.channel.topic
        if topic and "UserID:" in topic:
            try:
                creator_id_str = topic.split("UserID:")[1].strip()
                creator_id = int(creator_id_str)
                creator = member.guild.get_member(creator_id)
            except (ValueError, IndexError):
                print(f"Не удалось извлечь ID создателя из топика: {topic}")

        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(view=self)
        
        embed = discord.Embed(
            title="🔒 Тикет закрыт",
            description=f"Тикет был закрыт пользователем {member.mention}.\nКанал скоро будет удален или заархивирован.",
            color=discord.Color.red()
        )
        await interaction.channel.send(embed=embed)
        
        if creator:
            await interaction.channel.set_permissions(creator, overwrite=discord.PermissionOverwrite(read_messages=False, send_messages=False))
            await interaction.channel.send(f"Канал стал невидимым для создателя тикета ({creator.mention}).")
        else:
            await interaction.channel.send("Критическая ошибка: не удалось лишить создателя прав доступа.")
        
        current_name = interaction.channel.name
        if not current_name.startswith("closed-"):
            new_name = f"closed-{current_name.replace('claimed-', '')}"
            await interaction.channel.edit(name=new_name)

class PersistentButtonsView(View):
    """
    Персистентный View для сообщения с правилами.
    Содержит кнопку верификации и кнопку тикета.
    """
    
    def __init__(self, bot: commands.Bot, timeout=None):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.stop_on_timeout = False
        
    @discord.ui.button(label="✅ Согласен с правилами", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: Button):
        member = interaction.user
        
        if not config.VERIFY_ROLE_ID:
            await interaction.response.send_message("❌ Роль верификации не настроена.", ephemeral=True)
            return

        role = interaction.guild.get_role(config.VERIFY_ROLE_ID)
        
        if not role:
            await interaction.response.send_message("❌ Не удалось найти роль верификации по ID.", ephemeral=True)
            return
            
        if role in member.roles:
            await interaction.response.send_message(f"Вы уже прошли верификацию.", ephemeral=True)
            return
            
        try:
            await member.add_roles(role, reason="Верификация по кнопке с правилами")
            await interaction.response.send_message(f"✅ Вы успешно прошли верификацию! \n\nℹ️ Если есть проблемы с отображение истории каналов - перезапустите Discord ", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав для выдачи этой роли.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Произошла ошибка при выдаче роли: {e}", ephemeral=True)
            print(f"Ошибка выдачи роли: {e}")

    @discord.ui.button(label="📨 Связаться с администрацией", style=discord.ButtonStyle.primary, custom_id="ticket_button")
    async def ticket_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())

    @discord.ui.button(label="/Команды бота", style=discord.ButtonStyle.secondary, custom_id="help_button")
    async def help_button(self, interaction: discord.Interaction, button: Button):
        try:
            await help_command.callback(interaction)
        except Exception as e:
            print(f"Ошибка при вызове help_command из view: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Произошла ошибка при вызове команды /help.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Произошла ошибка при вызове команды /help.", ephemeral=True)
            except discord.HTTPException:
                pass