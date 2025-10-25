import discord
from discord import app_commands, ui, TextStyle
import os
import re
from typing import Optional, Dict
import asyncio

# ===================================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И КЛАССЫ
# ===================================================================

def parse_text_colors(text: str) -> str:
    """
    Парсит кастомные теги {color:...} и превращает их в цветной текст для Discord.
    Пример: {color:red}Привет!{/color}
    """
    color_map = {
        "red": "31", "green": "32", "yellow": "33",
        "blue": "34", "magenta": "35", "cyan": "36", "white": "37"
    }

    def replace_color(match):
        color_name = match.group(1).lower()
        inner_text = match.group(2)
        code = color_map.get(color_name, "0")
        return f"```ansi\n\u001b[0;{code}m{inner_text}\n```"

    pattern = r'\{color:(\w+)\}(.*?)\{\/color\}'
    return re.sub(pattern, replace_color, text, flags=re.DOTALL)

PRESET_COLORS: Dict[str, discord.Color] = {
    "Бирюзовый (По умолчанию)": discord.Color.blurple(),
    "Красный": discord.Color.red(),
    "Зеленый": discord.Color.green(),
    "Синий": discord.Color.blue(),
    "Оранжевый": discord.Color.orange(),
    "Фиолетовый": discord.Color.purple(),
    "Золотой": discord.Color.gold(),
    "Серый": discord.Color.light_grey(),
    "Темно-красный": discord.Color.dark_red(),
    "Темно-синий": discord.Color.dark_blue(),
    "Почти черный": discord.Color.from_rgb(1, 1, 1),
}


class FieldSelect(ui.Select):
    """Выпадающий список для выбора поля для редактирования или удаления."""
    def __init__(self, view: 'GigaBuilderView'):
        self.view_ref = view
        options = [
            discord.SelectOption(label=f"Поле #{i+1}: {field.name[:80]}", value=str(i))
            for i, field in enumerate(view.embed.fields)
        ]

        if not options:
            options.append(discord.SelectOption(label="Полей для редактирования нет", value="-1", emoji="🤷‍♂️"))

        super().__init__(placeholder="Выберите поле для редактирования/удаления...",
                         min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "-1":
            return await interaction.response.send_message("Нет полей для выбора.", ephemeral=True)
        
        field_index = int(self.values[0])
        self.view_ref.selected_field_index = field_index
        
        field_action_view = ui.View(timeout=180)
        
        edit_button = ui.Button(label="Редактировать", style=discord.ButtonStyle.primary, emoji="✏️")
        delete_button = ui.Button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️")

        async def edit_callback(i: discord.Interaction):
            modal = FieldModal(self.view_ref, is_editing=True)
            await i.response.send_modal(modal)
            await interaction.delete_original_response()

        async def delete_callback(i: discord.Interaction):
            self.view_ref.embed.remove_field(self.view_ref.selected_field_index)
            await self.view_ref.update_preview()
            await interaction.delete_original_response()

        edit_button.callback = edit_callback
        delete_button.callback = delete_callback

        field_action_view.add_item(edit_button)
        field_action_view.add_item(delete_button)

        await interaction.response.send_message(
            f"Выбрано Поле #{field_index + 1}: **{self.view_ref.embed.fields[field_index].name}**.\n"
            "Что вы хотите сделать?",
            view=field_action_view,
            ephemeral=True
        )

# ===================================================================
# 2. МОДАЛЬНЫЕ ОКНА
# ===================================================================

class FieldModal(ui.Modal, title="Настройка поля"):
    def __init__(self, view: 'GigaBuilderView', is_editing: bool = False):
        super().__init__()
        self.view = view
        self.is_editing = is_editing
        
        self.inline_select = ui.Select(
            placeholder="Отображать в одну линию?",
            options=[
                discord.SelectOption(label="Да", value="yes", description="Поле будет встроено в строку с другими."),
                discord.SelectOption(label="Нет", value="no", description="Поле займет всю ширину."),
            ],
            min_values=1, max_values=1
        )
        
        if is_editing and view.selected_field_index is not None:
            field = view.embed.fields[view.selected_field_index]
            self.name.default = field.name
            self.value.default = field.value
            self.inline_select.default_values = ["yes"] if field.inline else ["no"]
        else:
            self.inline_select.default_values = ["no"]

        self.add_item(self.inline_select)

    name = ui.TextInput(label="Заголовок поля", max_length=256, required=True)
    value = ui.TextInput(label="Текст поля", style=TextStyle.paragraph, max_length=1024, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        is_inline = self.inline_select.values[0] == 'yes'
        
        if self.is_editing and self.view.selected_field_index is not None:
            self.view.embed.set_field_at(
                self.view.selected_field_index, 
                name=self.name.value, 
                value=self.value.value, 
                inline=is_inline
            )
        else:
            self.view.embed.add_field(name=self.name.value, value=self.value.value, inline=is_inline)
        
        await interaction.response.defer()
        await self.view.update_preview()


class MainSettingsModal(ui.Modal, title="Основные настройки"):
    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view
        self.title_input.default = view.embed.title
        self.title_url_input.default = view.embed.url
        self.description_input.default = view.embed.description
        if view.embed.color:
            self.color_input.default = f"#{view.embed.color.value:06x}"
        self.timestamp_input.default = "да" if view.embed.timestamp else "нет"

    title_input = ui.TextInput(label="Заголовок", required=False, max_length=256)
    title_url_input = ui.TextInput(label="URL для заголовка (необязательно)", required=False)
    description_input = ui.TextInput(label="Описание", style=TextStyle.paragraph, required=False, max_length=4000)
    color_input = ui.TextInput(label="Цвет (HEX, например #ff00ff)", required=False, max_length=7, placeholder="#008080")
    timestamp_input = ui.TextInput(label="Включить время? (да/нет)", placeholder="нет", required=False, max_length=3)
    
    async def on_submit(self, interaction: discord.Interaction):
        self.view.embed.title = self.title_input.value or None
        self.view.embed.url = self.title_url_input.value or None
        self.view.embed.description = self.description_input.value or None
        
        if self.color_input.value:
            try:
                hex_color = self.color_input.value.strip().lstrip("#")
                if len(hex_color) == 0:
                    self.view.embed.color = None
                else:
                    self.view.embed.color = discord.Color(int(hex_color, 16))
            except ValueError:
                await interaction.response.send_message("❌ Неверный формат цвета HEX! Используйте формат `#RRGGBB`.", ephemeral=True)
                return

        if self.timestamp_input.value.lower() == 'да':
            self.view.embed.timestamp = discord.utils.utcnow()
        else:
            self.view.embed.timestamp = None
            
        await interaction.response.defer()
        await self.view.update_preview()

class ContentModal(ui.Modal, title="Текст сообщения"):
    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view
        self.content_input.default = view.message_content

    content_input = ui.TextInput(
        label="Текст над эмбедом",
        style=TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Здесь можно упомянуть @роль или @everyone..."
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.view.message_content = self.content_input.value or None
        await interaction.response.send_message("✅ Текст сообщения обновлен.", ephemeral=True, delete_after=5)

class ReorderFieldsView(ui.View):
    def __init__(self, builder_view: 'GigaBuilderView'):
        super().__init__(timeout=300)
        self.builder_view = builder_view
        
        field_options = [
            discord.SelectOption(label=f"Поле #{i+1}: {f.name[:80]}", value=str(i))
            for i, f in enumerate(builder_view.embed.fields)
        ]
        
        self.from_select = ui.Select(placeholder="Какое поле переместить?", options=field_options, min_values=1, max_values=1)
        self.to_select = ui.Select(placeholder="Переместить ПЕРЕД каким полем?", options=field_options, min_values=1, max_values=1)

        self.from_select.callback = self.on_select
        self.to_select.callback = self.on_select
        
        self.add_item(self.from_select)
        self.add_item(self.to_select)

    async def on_select(self, interaction: discord.Interaction):
        if not self.from_select.values or not self.to_select.values:
            return await interaction.response.defer()
        
        from_index = int(self.from_select.values[0])
        to_index = int(self.to_select.values[0])
        
        if from_index == to_index:
            return await interaction.response.send_message("❌ Нельзя переместить поле на его же место.", ephemeral=True)
            
        field_to_move = self.builder_view.embed.fields.pop(from_index)
        self.builder_view.embed.fields.insert(to_index, field_to_move)

        await interaction.response.edit_message(content="✅ Порядок полей изменен.", view=None)
        await self.builder_view.update_preview()
        self.stop()

class AuthorModal(ui.Modal, title="Настройка автора"):
    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view
        author = view.embed.author
        if author:
            self.name.default = author.name
            self.url.default = author.url
            self.icon_url.default = author.icon_url
    name = ui.TextInput(label="Имя автора", required=False, max_length=256)
    url = ui.TextInput(label="URL автора (необязательно)", required=False)
    icon_url = ui.TextInput(label="URL иконки автора (необязательно)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if self.name.value:
            self.view.embed.set_author(
                name=self.name.value,
                url=self.url.value or None,
                icon_url=self.icon_url.value or None
            )
        else:
            self.view.embed.remove_author()
        await interaction.response.defer()
        await self.view.update_preview()

class FooterModal(ui.Modal, title="Настройка футера"):
    def __init__(self, view: 'GigaBuilderView'):
        super().__init__()
        self.view = view
        footer = view.embed.footer
        if footer:
            self.text.default = footer.text
            self.icon_url.default = footer.icon_url
    text = ui.TextInput(label="Текст футера", required=False, max_length=2048)
    icon_url = ui.TextInput(label="URL иконки футера (необязательно)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if self.text.value:
            self.view.embed.set_footer(
                text=self.text.value,
                icon_url=self.icon_url.value or None
            )
        else:
            self.view.embed.remove_footer()
        await interaction.response.defer()
        await self.view.update_preview()

class ImageModal(ui.Modal, title="Настройка изображения по URL"):
    def __init__(self, view: 'GigaBuilderView', image_type: str):
        super().__init__()
        self.view = view
        self.image_type = image_type
        if image_type == 'image' and view.embed.image:
            self.url.default = view.embed.image.url
        elif image_type == 'thumbnail' and view.embed.thumbnail:
            self.url.default = view.embed.thumbnail.url
            
    url = ui.TextInput(label="URL изображения", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if self.image_type == 'image':
            self.view.embed.set_image(url=self.url.value or None)
        else:
            self.view.embed.set_thumbnail(url=self.url.value or None)
        await interaction.response.defer()
        await self.view.update_preview()

# ===================================================================
# ИСПРАВЛЕННЫЙ КЛАСС: View для выбора источника изображения
# ===================================================================

class ImageActionView(ui.View):
    def __init__(self, builder_view: 'GigaBuilderView', image_type: str):
        super().__init__(timeout=180)
        self.builder_view = builder_view
        self.image_type = image_type

    @ui.button(label="Загрузить файл", style=discord.ButtonStyle.success, emoji="🖥️")
    async def upload_file(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()

        prompt_message = (
            f"**Пожалуйста, отправьте {'изображение' if self.image_type == 'image' else 'миниатюру'} "
            f"(картинку или .gif) в этот канал в течение 60 секунд.**"
        )
        
        prompt_message_obj = await interaction.followup.send(prompt_message, ephemeral=True)

        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel and m.attachments

        try:
            msg = await self.builder_view.client.wait_for("message", timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await prompt_message_obj.delete()
            await interaction.followup.send("⏰ Время вышло. Попробуйте еще раз.", ephemeral=True)
            return

        attachment = msg.attachments[0]
        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            await interaction.followup.send("❌ Прикрепленный файл не является изображением.", ephemeral=True)
            await msg.delete()
            await prompt_message_obj.delete()
            return

        LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
        if not LOG_CHANNEL_ID:
            await interaction.followup.send("❌ Переменная окружения LOG_CHANNEL_ID не найдена.", ephemeral=True)
            await msg.delete()
            await prompt_message_obj.delete()
            return

        try:
            log_channel = await self.builder_view.client.fetch_channel(int(LOG_CHANNEL_ID))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("❌ Лог-канал не найден. Проверьте LOG_CHANNEL_ID в .env файле.", ephemeral=True)
            await msg.delete()
            await prompt_message_obj.delete()
            return
        
        try:
            log_message = await log_channel.send(file=await attachment.to_file())
            new_image_url = log_message.attachments[0].url
            
            if self.image_type == 'image':
                self.builder_view.embed.set_image(url=new_image_url)
            else:
                self.builder_view.embed.set_thumbnail(url=new_image_url)

        except Exception as e:
            print(f"Ошибка при пересылке изображения в лог-канал: {e}")
            await interaction.followup.send("❌ Произошла ошибка при обработке изображения.", ephemeral=True)
            await msg.delete()
            await prompt_message_obj.delete()
            return

        await self.builder_view.update_preview()
        
        await msg.delete()
        await prompt_message_obj.delete()
        
        self.stop()

    @ui.button(label="Вставить URL", style=discord.ButtonStyle.primary, emoji="🔗")
    async def use_url(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ImageModal(self.builder_view, self.image_type))
        await interaction.delete_original_response()
        self.stop()


# ===================================================================
# 3. ГЛАВНАЯ ПАНЕЛЬ "ГИГА-КОНСТРУКТОРА" (VIEW)
# ===================================================================

class GigaBuilderView(ui.View):
    def __init__(self, author: discord.User, target_channel: discord.TextChannel, role_to_mention: Optional[discord.Role], client: discord.Client):
        super().__init__(timeout=3600)
        self.author = author
        self.target_channel = target_channel
        self.role_to_mention = role_to_mention
        self.client = client
        self.message: Optional[discord.InteractionMessage] = None
        self.selected_field_index: Optional[int] = None
        self.message_content: Optional[str] = None
        self.embed = discord.Embed(
            title="Заголовок",
            description="Текст ...",
            color=discord.Color.blurple()
        )
        self.add_item(self.ColorSelect())

    class ColorSelect(ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label=name, value=name, emoji="🎨")
                for name in PRESET_COLORS.keys()
            ]
            super().__init__(placeholder="🎨 Выбрать готовый цвет...", min_values=1, max_values=1, options=options, row=1)
        
        async def callback(self, interaction: discord.Interaction):
            view: GigaBuilderView = self.view
            color_name = self.values[0]
            view.embed.color = PRESET_COLORS[color_name]
            await interaction.response.defer()
            await view.update_preview()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item) -> None:
        print(f"Произошла ошибка в GigaBuilderView: {error}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"Произошла непредвиденная ошибка: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Произошла непредвиденная ошибка: {error}", ephemeral=True)
        except (discord.NotFound, discord.InteractionResponded):
            print("Не удалось отправить сообщение об ошибке пользователю.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Это не ваш конструктор!", ephemeral=True, delete_after=5)
            return False
        return True

    async def update_preview(self):
        """Обновляет предпросмотр."""
        if self.message:
            try:
                for item in self.children:
                    if isinstance(item, FieldSelect):
                        self.remove_item(item)
                
                await self.message.edit(embed=self.embed, view=self)
            except discord.errors.NotFound:
                print("Сообщение для обновления не найдено, возможно оно было удалено.")
                self.stop()

    @ui.button(label="📝 Основное", style=discord.ButtonStyle.primary, row=0)
    async def main_settings_button(self, i: discord.Interaction, b: ui.Button):
        await i.response.send_modal(MainSettingsModal(self))

    @ui.button(label="✍️ Автор", style=discord.ButtonStyle.secondary, row=0)
    async def author_button(self, i: discord.Interaction, b: ui.Button):
        await i.response.send_modal(AuthorModal(self))

    @ui.button(label="🦶 Футер", style=discord.ButtonStyle.secondary, row=0)
    async def footer_button(self, i: discord.Interaction, b: ui.Button):
        await i.response.send_modal(FooterModal(self))

    @ui.button(label="💬 Текст сообщения", style=discord.ButtonStyle.secondary, row=0)
    async def content_button(self, i: discord.Interaction, b: ui.Button):
        await i.response.send_modal(ContentModal(self))

    @ui.button(label="🖼️ Изображение", style=discord.ButtonStyle.secondary, row=2)
    async def image_button(self, i: discord.Interaction, b: ui.Button):
        view = ImageActionView(self, image_type='image')
        await i.response.send_message("Выберите источник изображения:", view=view, ephemeral=True)
        

    @ui.button(label="📌 Превью", style=discord.ButtonStyle.secondary, row=2)
    async def thumbnail_button(self, i: discord.Interaction, b: ui.Button):
        view = ImageActionView(self, image_type='thumbnail')
        await i.response.send_message("Выберите источник миниатюры:", view=view, ephemeral=True)
    
    @ui.button(label="[+] Добавить поле", style=discord.ButtonStyle.success, row=3)
    async def add_field_button(self, i: discord.Interaction, b: ui.Button):
        if len(self.embed.fields) >= 25:
            return await i.response.send_message("❌ Достигнут лимит в 25 полей!", ephemeral=True)
        await i.response.send_modal(FieldModal(self))

    @ui.button(label="✏️ Изменить/Удалить поле", style=discord.ButtonStyle.primary, row=3)
    async def edit_delete_field_button(self, i: discord.Interaction, b: ui.Button):
        if not self.embed.fields:
            return await i.response.send_message("Нет полей для редактирования или удаления.", ephemeral=True)
        
        edit_view = ui.View(timeout=180)
        edit_view.add_item(FieldSelect(self))
        await i.response.send_message("Выберите поле:", view=edit_view, ephemeral=True)

    @ui.button(label="⇅ Порядок полей", style=discord.ButtonStyle.secondary, row=3)
    async def reorder_fields_button(self, i: discord.Interaction, b: ui.Button):
        if len(self.embed.fields) < 2:
            return await i.response.send_message("Нужно как минимум 2 поля для изменения их порядка.", ephemeral=True)
        await i.response.send_message("Выберите, какое поле и куда переместить:", view=ReorderFieldsView(self), ephemeral=True)

    @ui.button(label="➖ Разделитель", style=discord.ButtonStyle.secondary, row=3)
    async def add_separator_button(self, i: discord.Interaction, b: ui.Button):
        if len(self.embed.fields) >= 25:
            return await i.response.send_message("❌ Достигнут лимит в 25 полей!", ephemeral=True)
        self.embed.add_field(name="\u200b", value="\u200b", inline=False)
        await i.response.defer()
        await self.update_preview()

    @ui.button(label="✅ Опубликовать", style=discord.ButtonStyle.success, row=4)
    async def publish_button(self, i: discord.Interaction, b: ui.Button):
        final_embed = self.embed.copy()
        
        if final_embed.description:
            final_embed.description = parse_text_colors(final_embed.description)
        for idx, field in enumerate(final_embed.fields):
            final_embed.set_field_at(
                idx,
                name=field.name,
                value=parse_text_colors(field.value),
                inline=field.inline
            )
        
        content = self.message_content or ""
        mention_text = self.role_to_mention.mention if self.role_to_mention else ""
        final_content = f"{mention_text} {content}".strip()

        await self.target_channel.send(content=final_content or None, embed=final_embed)
        
        self.clear_items()
        await i.response.edit_message(content="✅ **Анонс успешно опубликован!**", view=None, embed=None)
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.danger, row=4)
    async def cancel_button(self, i: discord.Interaction, b: ui.Button):
        self.clear_items()
        await i.response.edit_message(content="❌ Конструктор закрыт.", view=None, embed=None)
        self.stop()

# ===================================================================
# 4. КОМАНДА ЗАПУСКА
# ===================================================================

@app_commands.command(name="constructor", description="Запустить интерактивный конструктор анонсов")
@app_commands.describe(
    channel="Канал для публикации анонса.",
    mention_role="Роль для упоминания при публикации."
)
async def constructor(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    mention_role: Optional[discord.Role] = None
):
    allowed_roles = list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else []
    user_roles = [role.id for role in interaction.user.roles]
    
    if not interaction.user.guild_permissions.administrator and not set(allowed_roles) & set(user_roles):
        await interaction.response.send_message(
            "❌ **Доступ закрыт!** У вас нет прав администратора или необходимой роли для использования этой команды.",
            ephemeral=True
        )
        return

    view = GigaBuilderView(
        author=interaction.user,
        target_channel=channel,
        role_to_mention=mention_role,
        client=interaction.client
    )
    
    await interaction.response.send_message(
        "**🚀 Запущен конструктор анонсов!**\n"
        "Используйте кнопки ниже для создания и редактирования вашего сообщения. "
        "Предпросмотр будет обновляться в реальном времени.",
        embed=view.embed,
        view=view,
        ephemeral=True
    )
    view.message = await interaction.original_response()