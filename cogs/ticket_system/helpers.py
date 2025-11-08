import discord
import datetime
import config.settings as config
from discord.ext import commands

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
    """Генерирует имя канала для тикета."""
    clean_subject = "".join(c for c in subject if c.isalnum() or c == ' ').strip().replace(' ', '-')[:15]
    clean_name = "".join(c for c in user_name if c.isalnum() or c == ' ').strip().replace(' ', '-')[:10]
    return f"ticket-{number:04d}-{clean_name}-{clean_subject}"

async def send_initial_ticket_message(channel: discord.TextChannel, user: discord.Member, subject: str, description: str):

    from .views import TicketManagementView

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
    
    embed.add_field(name="Подробное описание проблемы", value=description, inline=False)
    embed.set_footer(text=f"Тикет создан пользователем {user.name}")
    
    await channel.edit(topic=f"Тикет от пользователя {user.name}. UserID: {user.id}")

    await channel.send(f"{support_mention}, поступил новый тикет.", embed=embed, view=TicketManagementView())


async def claim_ticket_logic(interaction: discord.Interaction, original_message: discord.Message):
    
    from .views import TicketManagementView

    member = interaction.user
    
    if config.SUPPORT_ROLE_ID is None:
        await interaction.followup.send("❌ ID роли поддержки не настроен.", ephemeral=True)
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
        await interaction.followup.send("❌ Критическая ошибка: Не удалось найти создателя тикета.", ephemeral=True)
        return

    try:
        current_name = interaction.channel.name
        if not current_name.startswith("claimed-"):
            new_name = f"claimed-{current_name}"
            await interaction.channel.edit(name=new_name)
        else:
            await interaction.followup.send("Этот тикет уже был взят в работу.", ephemeral=True)
            return

        overwrite = discord.PermissionOverwrite(read_messages=True, send_messages=True,read_message_history=True)
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