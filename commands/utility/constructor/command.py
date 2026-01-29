"""
Slash-команда /constructor для запуска конструктора embed.
"""
import discord
from discord import app_commands
from typing import Optional
import os
import logging

from .views.main_view import GigaBuilderView

logger = logging.getLogger(__name__)


@app_commands.command(
    name="constructor",
    description="Запустить интерактивный конструктор анонсов"
)
@app_commands.describe(
    channel="Канал для публикации анонса",
    mention_role="Роль для упоминания при публикации"
)
async def constructor(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    mention_role: Optional[discord.Role] = None
):
    """
    Запускает интерактивный конструктор embed-сообщений.

    Позволяет:
    - Создавать и редактировать embed
    - Добавлять поля, изображения, автора, футер
    - Использовать шаблоны
    - Добавлять интерактивные кнопки
    - Планировать публикацию
    - Создавать треды для обсуждения
    """
    # Проверка прав
    allowed_roles = []
    allowed_roles_env = os.getenv("ALLOWED_ROLES", "")
    if allowed_roles_env:
        try:
            allowed_roles = [int(r.strip()) for r in allowed_roles_env.split(',') if r.strip()]
        except ValueError:
            logger.warning("Invalid ALLOWED_ROLES format in .env")

    user_roles = [role.id for role in interaction.user.roles]
    is_admin = interaction.user.guild_permissions.administrator
    has_allowed_role = bool(set(allowed_roles) & set(user_roles))

    if not is_admin and not has_allowed_role:
        await interaction.response.send_message(
            "❌ **Доступ закрыт!** У вас нет прав администратора "
            "или необходимой роли для использования этой команды.",
            ephemeral=True
        )
        return

    # Проверяем права на отправку в целевой канал
    bot_permissions = channel.permissions_for(interaction.guild.me)
    if not bot_permissions.send_messages or not bot_permissions.embed_links:
        await interaction.response.send_message(
            f"❌ Бот не имеет прав для отправки сообщений в {channel.mention}",
            ephemeral=True
        )
        return

    # Создаём view
    view = GigaBuilderView(
        author=interaction.user,
        target_channel=channel,
        role_to_mention=mention_role,
        client=interaction.client
    )

    # Отправляем конструктор
    await interaction.response.send_message(
        "**🚀 Запущен конструктор анонсов!**\n"
        "Используйте кнопки ниже для создания и редактирования вашего сообщения. "
        "Предпросмотр будет обновляться в реальном времени.\n\n"
        f"📍 Канал публикации: {channel.mention}"
        + (f"\n📢 Упоминание: {mention_role.mention}" if mention_role else ""),
        embed=view.embed,
        view=view,
        ephemeral=True
    )

    view.message = await interaction.original_response()
    logger.info(f"Constructor started by {interaction.user} for channel {channel.name}")


# Команда для отмены запланированных сообщений
@app_commands.command(
    name="schedule_cancel",
    description="Отменить запланированную публикацию"
)
@app_commands.describe(
    task_id="ID задачи (получен при планировании)"
)
async def schedule_cancel(
    interaction: discord.Interaction,
    task_id: str
):
    """Отменяет запланированную публикацию."""
    from .utils.scheduler import cancel_scheduled, get_scheduled_messages

    # Проверяем что это наше сообщение
    scheduled = get_scheduled_messages(interaction.guild_id)
    task = next((m for m in scheduled if m.id == task_id), None)

    if not task:
        return await interaction.response.send_message(
            f"❌ Задача `{task_id}` не найдена.",
            ephemeral=True
        )

    # Проверяем права (автор или админ)
    if task.author_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Вы можете отменить только свои запланированные публикации.",
            ephemeral=True
        )

    success = await cancel_scheduled(task_id)

    if success:
        await interaction.response.send_message(
            f"✅ Запланированная публикация `{task_id}` отменена.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Не удалось отменить публикацию.",
            ephemeral=True
        )


# Команда для просмотра запланированных сообщений
@app_commands.command(
    name="schedule_list",
    description="Показать запланированные публикации"
)
async def schedule_list(interaction: discord.Interaction):
    """Показывает список запланированных публикаций."""
    from .utils.scheduler import get_scheduled_messages
    from datetime import datetime

    scheduled = get_scheduled_messages(interaction.guild_id)

    if not scheduled:
        return await interaction.response.send_message(
            "📋 Нет запланированных публикаций.",
            ephemeral=True
        )

    text = "**📋 Запланированные публикации:**\n\n"

    for msg in sorted(scheduled, key=lambda m: m.publish_at):
        channel = interaction.guild.get_channel(msg.channel_id)
        channel_name = channel.mention if channel else f"ID: {msg.channel_id}"

        publish_dt = datetime.fromisoformat(msg.publish_at)
        time_str = publish_dt.strftime("%d.%m.%Y %H:%M")

        author = interaction.guild.get_member(msg.author_id)
        author_name = author.display_name if author else f"ID: {msg.author_id}"

        text += f"🔑 `{msg.id}` | 📅 {time_str} | 📍 {channel_name} | 👤 {author_name}\n"

    await interaction.response.send_message(text, ephemeral=True)
