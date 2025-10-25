import discord
from discord import app_commands, ui, TextStyle
from config import settings
import os
import re

class AnnouncePreviewView(ui.View):
    def __init__(self, embed: discord.Embed, target_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.embed = embed
        self.target_channel = target_channel

    @ui.button(label="✅ Отправить", style=discord.ButtonStyle.green)
    async def send_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.target_channel.send(embed=self.embed)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ **Анонс успешно отправлен!**", view=self)
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ **Отправка анонса отменена.**", view=self)
        self.stop()


class AnnounceModal(ui.Modal, title="Создание нового анонса"):
    def __init__(self, target_channel: discord.TextChannel, role: discord.Role, image_url: str, thumbnail_url: str):
        super().__init__()
        self.target_channel = target_channel
        self.role = role
        self.image_url = image_url
        self.thumbnail_url = thumbnail_url

    custom_title = ui.TextInput(
        label="Пользовательский заголовок (необязательно)",
        placeholder="Оставьте пустым для стандартного заголовка",
        required=False,
        max_length=256
    )
    
    message_input = ui.TextInput(
        label="Текст объявления (поддерживает Markdown)",
        style=TextStyle.paragraph,
        placeholder="Введите ваше объявление здесь...",
        required=True,
        max_length=4000
    )

    color_hex = ui.TextInput(
        label="Цвет в HEX-формате (необязательно)",
        placeholder="Например: #5865F2 или оставьте пустым для стандартного",
        required=False,
        max_length=7
    )

    async def on_submit(self, interaction: discord.Interaction):
        message = self.message_input.value
        title = self.custom_title.value or "📢 Официальное объявление"
        color_input = self.color_hex.value

        try:
            color = settings.ANNOUNCE["COLOR"]
            if color_input and re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color_input):
                color = int(color_input.lstrip('#'), 16)

            embed = discord.Embed(
                title=title,
                description=f"{self.role.mention if self.role else ''}\n\n{message}",
                color=color
            )
            embed.set_footer(
                text=f"Анонс от {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url
            )
            
            if self.image_url:
                embed.set_image(url=self.image_url)
            if self.thumbnail_url:
                embed.set_thumbnail(url=self.thumbnail_url)

            view = AnnouncePreviewView(embed=embed, target_channel=self.target_channel)
            await interaction.response.send_message(
                "**Предпросмотр вашего анонса:**\nВыглядит хорошо? Нажмите 'Отправить' для публикации.",
                embed=embed,
                view=view,
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(f"❌ Произошла ошибка при создании предпросмотра: {str(e)}", ephemeral=True)


@app_commands.command(name="announce", description="Создать гибко настраиваемое объявление с предпросмотром")
@app_commands.describe(
    channel="Канал для отправки (по умолчанию официальный)",
    mention_role="Роль для упоминания (ID или название)",
    image_url="URL картинки для вставки в анонс",
    thumbnail_url="URL маленькой иконки (справа от заголовка)"
)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    mention_role: str = None,
    image_url: str = None,
    thumbnail_url: str = None
):
    allowed_roles = list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else []
    user_roles = [role.id for role in interaction.user.roles]
    
    if not interaction.user.guild_permissions.administrator and not set(allowed_roles) & set(user_roles):
        await interaction.response.send_message(
            "❌ **Доступ закрыт!** У вас нет прав администратора или необходимой роли для использования этой команды.",
            ephemeral=True
        )
        return

    try:
        announce_config = settings.ANNOUNCE
        default_channel_id = announce_config["DEFAULT_CHANNEL"]
        target_channel = channel or interaction.guild.get_channel(default_channel_id)
        
        if not target_channel:
            return await interaction.response.send_message("❌ Официальный канал не настроен!", ephemeral=True)

        role_to_mention = None
        if mention_role:
            try:
                role_to_mention = interaction.guild.get_role(int(mention_role))
            except ValueError:
                role_to_mention = discord.utils.get(interaction.guild.roles, name=mention_role)
            
            if not role_to_mention:
                return await interaction.response.send_message("❌ Указанная роль не найдена!", ephemeral=True)

        modal = AnnounceModal(
            target_channel=target_channel, 
            role=role_to_mention,
            image_url=image_url,
            thumbnail_url=thumbnail_url
        )
        await interaction.response.send_modal(modal)

    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(f"❌ Произошла критическая ошибка при вызове команды: {str(e)}", ephemeral=True)


@announce.autocomplete("mention_role")
async def role_autocomplete(interaction: discord.Interaction, current: str):
    try:
        allowed_roles = list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else []
        
        choices = [
            app_commands.Choice(
                name=f"{role.name} {'✅' if role.id in allowed_roles else ''}",
                value=str(role.id)
            )
            for role in interaction.guild.roles
            if current.lower() in role.name.lower() and role.name != "@everyone"
        ]
        return choices[:25]
    except Exception as e:
        return []