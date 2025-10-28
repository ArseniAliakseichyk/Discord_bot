import discord
from discord import app_commands 
from discord.ext import commands 
from discord.ui import Button, View, Modal, TextInput
import os 
import datetime
import uuid
import conf.config as config

TICKET_COUNTER_FILE = "ticket_counter.txt" 

def get_next_ticket_number():
    """Считывает, увеличивает и записывает следующий номер тикета."""
    try:
        with open(TICKET_COUNTER_FILE, 'r') as f:
            last_number = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        last_number = 0

    next_number = last_number + 1
    
    with open(TICKET_COUNTER_FILE, 'w') as f:
        f.write(str(next_number))
        
    return next_number

def get_ticket_channel_name(user_name, number, subject):
    # Заменяем пробелы и символы, запрещенные в именах каналов, на дефисы
    # Добавляем тему для информативности, обрезая до 15 символов
    clean_subject = "".join(c for c in subject if c.isalnum() or c == ' ').strip().replace(' ', '-')[:15]
    clean_name = "".join(c for c in user_name if c.isalnum() or c == ' ').strip().replace(' ', '-')[:10]
    # discord автоматически приводит к нижнему регистру
    return f"ticket-{number:04d}-{clean_name}-{clean_subject}"

async def send_initial_ticket_message(channel: discord.TextChannel, user: discord.Member, subject: str, description: str):
    """
    Отправляет первое сообщение в канале тикета, видимое только администрации.
    Сообщение содержит всю информацию о запросе и кнопки управления.
    """
    support_role = channel.guild.get_role(config.SUPPORT_ROLE_ID)
    support_mention = support_role.mention if support_role else "Администрация/Поддержка"

    embed = discord.Embed(
        title=f"📨 НОВЫЙ ЗАПРОС (Ожидает обработки): {subject}",
        description=(
            f"**Пользователь:** {user.mention} ({user.id})\n"
            f"**Время создания:** {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        ),
        color=discord.Color.orange()
    )
    
    # 0. Первое поле: Подробное описание (будет использоваться при взятии тикета)
    embed.add_field(name="Подробное описание проблемы", value=description, inline=False)
    
    # 1. Второе поле: Действия для администрации
    # embed.add_field(
    #     name="Дальнейшие действия (Только для Администрации)",
    #     value=(
    #         f"**{support_mention}**, нажмите 'Взять в работу', чтобы:\n"
    #         "1. Сделать канал видимым для пользователя.\n"
    #         "2. Уведомить его, что вы занялись вопросом."
    #     ),
    #     inline=False
    # )
    
    embed.set_footer(text=f"Тикет создан пользователем {user.name}")
    
    await channel.edit(topic=f"Тикет от пользователя {user.name}. UserID: {user.id}")
    
    # Отправляем сообщение, которое видно только саппорту
    await channel.send(f"{support_mention}, поступил новый тикет.", embed=embed, view=TicketManagementView())


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
            await interaction.followup.send("❌ Настройка системы тикетов не завершена. Отсутствуют ID категории или роли поддержки.", ephemeral=True)
            return

        category = guild.get_channel(config.TICKET_CATEGORY_ID)
        if not category:
            await interaction.followup.send("❌ Не удалось найти категорию для тикетов. Проверьте TICKET_CATEGORY_ID.", ephemeral=True)
            return
            
        ticket_number = get_next_ticket_number()
        channel_name = get_ticket_channel_name(user.name, ticket_number, ticket_subject)
        
        try:
            
            support_role = guild.get_role(config.SUPPORT_ROLE_ID)
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=False, send_messages=False), # DENY for the user initially!
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
                f"✅ Ваш запрос отправлен! Ожидайте, пока администрация возьмет его в работу. "
                f"Как только это произойдет, канал с `тикитом` станет вам доступен. "
                f"Внимание: Вы **не** увидите этот канал, пока его не откроет сотрудник поддержки.",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(f"❌ Произошла ошибка при создании тикета: {e}", ephemeral=True)
            print(f"Ошибка создания тикета: {e}")

async def claim_ticket_logic(interaction: discord.Interaction, original_message: discord.Message):
    
    member = interaction.user

    if config.SUPPORT_ROLE_ID is None:
        await interaction.followup.send("❌ ID роли поддержки не настроен. Обратитесь к администратору.", ephemeral=True)
        return

    support_role = member.guild.get_role(config.SUPPORT_ROLE_ID)
    if not (support_role and member in support_role.members):
        await interaction.followup.send("❌ У вас нет прав для взятия тикета в работу.", ephemeral=True)
        return

    creator_id = None
    creator = None
    topic = interaction.channel.topic
    if topic and "UserID:" in topic:
        try:
            creator_id_str = topic.split("UserID:")[1].strip()
            creator_id = int(creator_id_str)
            creator = interaction.guild.get_member(creator_id)
        except (ValueError, IndexError):
            print(f"Не удалось извлечь ID создателя из топика: {topic}")

    if not creator:
        await interaction.followup.send("❌ Критическая ошибка: Не удалось найти создателя тикета. Не могу открыть канал.", ephemeral=True)
        return

    try:
        current_name = interaction.channel.name
        if not current_name.startswith("claimed-"):
            new_name = f"claimed-{current_name}"
            await interaction.channel.edit(name=new_name)
        else:
             await interaction.followup.send("Этот тикет уже был взят в работу.", ephemeral=True)
             return

        overwrite = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        await interaction.channel.set_permissions(creator, overwrite=overwrite)
        
        embed = original_message.embeds[0]
        
        fields_to_readd = embed.fields[:]
        embed.clear_fields()

        description_text = ""
        if fields_to_readd:
            field = fields_to_readd.pop(0) 
            description_text = field.value 
            embed.add_field(name=field.name, value=field.value, inline=field.inline)

        embed.add_field(name="✅ В работе у", value=f"{member.mention}", inline=False)
        
        for field in fields_to_readd:
            embed.add_field(name=field.name, value=field.value, inline=field.inline)

        embed.color = discord.Color.green()
        embed.title = embed.title.replace("Ожидает обработки", "ОТКРЫТ")
        
        new_view = TicketManagementView(is_claimed=True)
        await original_message.edit(embed=embed, view=new_view)
        
        await interaction.channel.send(
            f"{creator.mention}, ваш тикет стал **открытым**! "
            f"Им занялся администратор {member.mention}."
        )

        await interaction.channel.send(f"**Ваш текст обращения:**\n```\n{description_text}```")

    except Exception as e:
        await interaction.followup.send(f"❌ Произошла ошибка при обработке тикета: {e}", ephemeral=True)
        print(f"Ошибка claim_ticket_logic: {e}")


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
            await interaction.response.send_message("❌ Роль верификации не настроена. Обратитесь к администратору.", ephemeral=True)
            return

        role = interaction.guild.get_role(config.VERIFY_ROLE_ID)
        
        if not role:
            await interaction.response.send_message("❌ Не удалось найти роль верификации по ID. Обратитесь к администратору.", ephemeral=True)
            return
            
        if role in member.roles:
            await interaction.response.send_message(f"Вы уже прошли верификацию.", ephemeral=True)
            return
            
        try:
            await member.add_roles(role, reason="Верификация по кнопке с правилами")
            await interaction.response.send_message(f"✅ Вы успешно прошли верификацию и получили доступ к серверу!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав для выдачи этой роли. Обратитесь к администратору.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Произошла ошибка при выдаче роли: {e}", ephemeral=True)
            print(f"Ошибка выдачи роли: {e}")

    @discord.ui.button(label="📨 Связаться с администрацией", style=discord.ButtonStyle.danger, custom_id="ticket_button")
    async def ticket_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TicketModal())


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
    @commands.has_permissions(administrator=True) 
    async def send_rules_message(self, interaction: discord.Interaction): 
        
        embed = discord.Embed(
            title="📜 Правила и поддержка",
            description=(
                "✅ Нажимая **'Согласен'**, вы подтверждаете, что принимаете правила и получите доступ к серверу.\n\n"
                "📨 Если у вас возник вопрос или проблема, нажмите **'Связаться с администрацией'**, чтобы создать тикет."
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Спасибо за понимание!")

        await interaction.response.send_message("✅ Сообщение с правилами отправлено в канал.", ephemeral=True)

        await interaction.channel.send(embed=embed, view=PersistentButtonsView(self.bot))

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleButtonCog(bot))
