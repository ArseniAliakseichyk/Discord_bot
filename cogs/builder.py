"""The /constructor command: an interactive embed builder."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import discord
from discord import TextStyle, app_commands, ui
from discord.ext import commands

from core.bot import MusicBot
from utils.checks import can_announce
from utils.validation import is_http_url

logger = logging.getLogger("bot.builder")

# Mentions are allowed only on the final publish send.
_PUBLISH_MENTIONS = discord.AllowedMentions(everyone=True, roles=True, users=True)


# =================================================================== #
#  1. Helpers and constants
# =================================================================== #
def parse_text_colors(text: str) -> str:
    """Turn ``{color:red}...{/color}`` tags into ANSI-colored code blocks."""
    color_map = {
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "white": "37",
    }

    def replace_color(match: re.Match[str]) -> str:
        color_name = match.group(1).lower()
        inner_text = match.group(2)
        code = color_map.get(color_name, "0")
        return f"```ansi\n[0;{code}m{inner_text}\n```"

    pattern = r"\{color:(\w+)\}(.*?)\{\/color\}"
    return re.sub(pattern, replace_color, text, flags=re.DOTALL)


PRESET_COLORS: dict[str, discord.Color] = {
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
    """Dropdown to pick a field to edit or delete."""

    def __init__(self, view: "GigaBuilderView") -> None:
        self.view_ref = view
        options = [
            discord.SelectOption(label=f"Поле #{i + 1}: {field.name[:80]}", value=str(i))
            for i, field in enumerate(view.embed.fields)
        ]
        if not options:
            options.append(
                discord.SelectOption(
                    label="Полей для редактирования нет", value="-1", emoji="🤷‍♂️"
                )
            )
        super().__init__(
            placeholder="Выберите поле для редактирования/удаления...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "-1":
            await interaction.response.send_message(
                "Нет полей для выбора.", ephemeral=True
            )
            return

        field_index = int(self.values[0])
        self.view_ref.selected_field_index = field_index
        field_action_view = ui.View(timeout=180)

        edit_button = ui.Button(
            label="Редактировать", style=discord.ButtonStyle.primary, emoji="✏️"
        )
        delete_button = ui.Button(
            label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️"
        )

        async def edit_callback(i: discord.Interaction) -> None:
            await i.response.send_modal(FieldModal(self.view_ref, is_editing=True))
            await interaction.delete_original_response()

        async def delete_callback(i: discord.Interaction) -> None:
            self.view_ref.embed.remove_field(self.view_ref.selected_field_index)
            await i.response.defer()
            await self.view_ref.update_preview()
            await interaction.delete_original_response()

        edit_button.callback = edit_callback
        delete_button.callback = delete_callback
        field_action_view.add_item(edit_button)
        field_action_view.add_item(delete_button)

        await interaction.response.send_message(
            f"Выбрано Поле #{field_index + 1}: "
            f"**{self.view_ref.embed.fields[field_index].name}**.\nЧто сделать?",
            view=field_action_view,
            ephemeral=True,
        )


# =================================================================== #
#  2. Modals
# =================================================================== #
class FieldModal(ui.Modal, title="Настройка поля"):
    def __init__(self, view: "GigaBuilderView", is_editing: bool = False) -> None:
        super().__init__()
        self.view = view
        self.is_editing = is_editing
        if is_editing and view.selected_field_index is not None:
            field = view.embed.fields[view.selected_field_index]
            self.name.default = field.name
            self.value.default = field.value
            self.is_inline_input.default = "да" if field.inline else "нет"
        else:
            self.is_inline_input.default = "нет"

    name = ui.TextInput(label="Заголовок поля", max_length=256, required=True)
    value = ui.TextInput(
        label="Текст поля", style=TextStyle.paragraph, max_length=1024, required=True
    )
    is_inline_input = ui.TextInput(
        label="В одну линию? (да/нет)", placeholder="нет", required=False, max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        is_inline = self.is_inline_input.value.lower().strip() == "да"
        if self.is_editing and self.view.selected_field_index is not None:
            self.view.embed.set_field_at(
                self.view.selected_field_index,
                name=self.name.value,
                value=self.value.value,
                inline=is_inline,
            )
        else:
            self.view.embed.add_field(
                name=self.name.value, value=self.value.value, inline=is_inline
            )
        await interaction.response.defer()
        await self.view.update_preview()


class MainSettingsModal(ui.Modal, title="Основные настройки"):
    def __init__(self, view: "GigaBuilderView") -> None:
        super().__init__()
        self.view = view
        self.title_input.default = view.embed.title
        self.title_url_input.default = view.embed.url
        self.description_input.default = view.embed.description
        if view.embed.color:
            self.color_input.default = f"#{view.embed.color.value:06x}"
        self.timestamp_input.default = "да" if view.embed.timestamp else "нет"

    title_input = ui.TextInput(label="Заголовок", required=False, max_length=256)
    title_url_input = ui.TextInput(label="URL заголовка (необязательно)", required=False)
    description_input = ui.TextInput(
        label="Описание", style=TextStyle.paragraph, required=False, max_length=4000
    )
    color_input = ui.TextInput(
        label="Цвет (HEX, #ff00ff)", required=False, max_length=7, placeholder="#008080"
    )
    timestamp_input = ui.TextInput(
        label="Включить время? (да/нет)", placeholder="нет", required=False, max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view.embed.title = self.title_input.value or None
        self.view.embed.url = self.title_url_input.value or None
        self.view.embed.description = self.description_input.value or None

        if self.color_input.value:
            try:
                hex_color = self.color_input.value.strip().lstrip("#")
                self.view.embed.color = (
                    discord.Color(int(hex_color, 16)) if hex_color else None
                )
            except ValueError:
                await interaction.response.send_message(
                    "❌ Неверный HEX-цвет! Формат `#RRGGBB`.", ephemeral=True
                )
                return

        self.view.embed.timestamp = (
            discord.utils.utcnow()
            if self.timestamp_input.value.lower() == "да"
            else None
        )
        await interaction.response.defer()
        await self.view.update_preview()


class ContentModal(ui.Modal, title="Текст сообщения"):
    def __init__(self, view: "GigaBuilderView") -> None:
        super().__init__()
        self.view = view
        self.content_input.default = view.message_content

    content_input = ui.TextInput(
        label="Текст над эмбедом",
        style=TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Здесь можно упомянуть @роль или @everyone...",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view.message_content = self.content_input.value or None
        await interaction.response.send_message(
            "✅ Текст сообщения обновлён.", ephemeral=True, delete_after=5
        )


class ReorderFieldsView(ui.View):
    def __init__(self, builder_view: "GigaBuilderView") -> None:
        super().__init__(timeout=300)
        self.builder_view = builder_view
        field_options = [
            discord.SelectOption(label=f"Поле #{i + 1}: {f.name[:80]}", value=str(i))
            for i, f in enumerate(builder_view.embed.fields)
        ]
        self.from_select = ui.Select(
            placeholder="Какое поле переместить?",
            options=field_options,
            min_values=1,
            max_values=1,
        )
        self.to_select = ui.Select(
            placeholder="Переместить ПЕРЕД каким полем?",
            options=field_options,
            min_values=1,
            max_values=1,
        )
        self.from_select.callback = self.on_select
        self.to_select.callback = self.on_select
        self.add_item(self.from_select)
        self.add_item(self.to_select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        if not self.from_select.values or not self.to_select.values:
            await interaction.response.defer()
            return
        from_index = int(self.from_select.values[0])
        to_index = int(self.to_select.values[0])
        if from_index == to_index:
            await interaction.response.send_message(
                "❌ Нельзя переместить поле на его же место.", ephemeral=True
            )
            return
        # Embed.fields returns a copy in discord.py 2.x, so rebuild the fields
        # explicitly instead of mutating that list (which would be a no-op).
        fields = [
            (f.name, f.value, f.inline) for f in self.builder_view.embed.fields
        ]
        fields.insert(to_index, fields.pop(from_index))
        self.builder_view.embed.clear_fields()
        for name, value, inline in fields:
            self.builder_view.embed.add_field(name=name, value=value, inline=inline)
        await interaction.response.edit_message(content="✅ Порядок изменён.", view=None)
        await self.builder_view.update_preview()
        self.stop()


class AuthorModal(ui.Modal, title="Настройка автора"):
    def __init__(self, view: "GigaBuilderView") -> None:
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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.name.value:
            self.view.embed.set_author(
                name=self.name.value,
                url=self.url.value or None,
                icon_url=self.icon_url.value or None,
            )
        else:
            self.view.embed.remove_author()
        await interaction.response.defer()
        await self.view.update_preview()


class FooterModal(ui.Modal, title="Настройка футера"):
    def __init__(self, view: "GigaBuilderView") -> None:
        super().__init__()
        self.view = view
        footer = view.embed.footer
        if footer:
            self.text.default = footer.text
            self.icon_url.default = footer.icon_url

    text = ui.TextInput(label="Текст футера", required=False, max_length=2048)
    icon_url = ui.TextInput(label="URL иконки футера (необязательно)", required=False)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.text.value:
            self.view.embed.set_footer(
                text=self.text.value, icon_url=self.icon_url.value or None
            )
        else:
            self.view.embed.remove_footer()
        await interaction.response.defer()
        await self.view.update_preview()


class ImageModal(ui.Modal, title="Изображение по URL"):
    def __init__(self, view: "GigaBuilderView", image_type: str) -> None:
        super().__init__()
        self.view = view
        self.image_type = image_type
        if image_type == "image" and view.embed.image:
            self.url.default = view.embed.image.url
        elif image_type == "thumbnail" and view.embed.thumbnail:
            self.url.default = view.embed.thumbnail.url

    url = ui.TextInput(label="URL изображения", required=False)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.url.value.strip()
        if value and not is_http_url(value):
            await interaction.response.send_message(
                "❌ Это не похоже на корректный URL (http/https).", ephemeral=True
            )
            return
        if self.image_type == "image":
            self.view.embed.set_image(url=value or None)
        else:
            self.view.embed.set_thumbnail(url=value or None)
        await interaction.response.defer()
        await self.view.update_preview()


class ImageActionView(ui.View):
    """Choose the image source: upload a file or paste a URL."""

    def __init__(self, builder_view: "GigaBuilderView", image_type: str) -> None:
        super().__init__(timeout=180)
        self.builder_view = builder_view
        self.image_type = image_type

    @ui.button(label="Загрузить файл", style=discord.ButtonStyle.success, emoji="🖥️")
    async def upload_file(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()

        what = "изображение" if self.image_type == "image" else "миниатюру"
        prompt = await interaction.followup.send(
            f"**Отправьте {what} (картинку или .gif) в этот канал в течение 60 секунд.**",
            ephemeral=True,
        )

        def check(message: discord.Message) -> bool:
            return (
                message.author == interaction.user
                and message.channel == interaction.channel
                and bool(message.attachments)
            )

        try:
            msg = await self.builder_view.bot.wait_for(
                "message", timeout=60.0, check=check
            )
        except asyncio.TimeoutError:
            await prompt.delete()
            await interaction.followup.send("⏰ Время вышло.", ephemeral=True)
            return

        attachment = msg.attachments[0]
        if not attachment.content_type or not attachment.content_type.startswith(
            "image/"
        ):
            await interaction.followup.send(
                "❌ Прикреплённый файл не является изображением.", ephemeral=True
            )
            await msg.delete()
            await prompt.delete()
            return

        log_channel_id = self.builder_view.bot.settings.log_channel_id
        if not log_channel_id:
            await interaction.followup.send(
                "❌ LOG_CHANNEL_ID не настроен — загрузка файлов недоступна.",
                ephemeral=True,
            )
            await msg.delete()
            await prompt.delete()
            return

        try:
            log_channel = await self.builder_view.bot.fetch_channel(log_channel_id)
            log_message = await log_channel.send(file=await attachment.to_file())  # type: ignore[union-attr]
            new_url = log_message.attachments[0].url
            if self.image_type == "image":
                self.builder_view.embed.set_image(url=new_url)
            else:
                self.builder_view.embed.set_thumbnail(url=new_url)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to store uploaded image in the log channel")
            await interaction.followup.send(
                "❌ Не удалось обработать изображение.", ephemeral=True
            )
            await msg.delete()
            await prompt.delete()
            return

        await self.builder_view.update_preview()
        await msg.delete()
        await prompt.delete()
        self.stop()

    @ui.button(label="Вставить URL", style=discord.ButtonStyle.primary, emoji="🔗")
    async def use_url(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(
            ImageModal(self.builder_view, self.image_type)
        )
        await interaction.delete_original_response()
        self.stop()


# =================================================================== #
#  3. Main builder panel
# =================================================================== #
class GigaBuilderView(ui.View):
    def __init__(
        self,
        author: discord.User | discord.Member,
        target_channel: discord.TextChannel,
        role_to_mention: Optional[discord.Role],
        bot: MusicBot,
    ) -> None:
        super().__init__(timeout=3600)
        self.author = author
        self.target_channel = target_channel
        self.role_to_mention = role_to_mention
        self.bot = bot
        self.message: Optional[discord.InteractionMessage] = None
        self.selected_field_index: Optional[int] = None
        self.message_content: Optional[str] = None
        self.embed = discord.Embed(
            title="Заголовок", description="Текст ...", color=discord.Color.blurple()
        )
        self.add_item(self.ColorSelect())

    class ColorSelect(ui.Select):
        def __init__(self) -> None:
            options = [
                discord.SelectOption(label=name, value=name, emoji="🎨")
                for name in PRESET_COLORS
            ]
            super().__init__(
                placeholder="🎨 Выбрать готовый цвет...",
                min_values=1,
                max_values=1,
                options=options,
                row=1,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            view: GigaBuilderView = self.view  # type: ignore[assignment]
            view.embed.color = PRESET_COLORS[self.values[0]]
            await interaction.response.defer()
            await view.update_preview()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: ui.Item
    ) -> None:
        logger.exception("Error in GigaBuilderView: %s", error)
        message = f"Произошла ошибка: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except (discord.NotFound, discord.InteractionResponded):
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Это не ваш конструктор!", ephemeral=True, delete_after=5
            )
            return False
        return True

    async def update_preview(self) -> None:
        if self.message is None:
            return
        try:
            for item in list(self.children):
                if isinstance(item, FieldSelect):
                    self.remove_item(item)
            await self.message.edit(embed=self.embed, view=self)
        except discord.NotFound:
            logger.warning("Builder preview message not found (deleted?)")
            self.stop()

    @ui.button(label="📝 Основное", style=discord.ButtonStyle.primary, row=0)
    async def main_settings_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_modal(MainSettingsModal(self))

    @ui.button(label="✍️ Автор", style=discord.ButtonStyle.secondary, row=0)
    async def author_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_modal(AuthorModal(self))

    @ui.button(label="🦶 Футер", style=discord.ButtonStyle.secondary, row=0)
    async def footer_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_modal(FooterModal(self))

    @ui.button(label="💬 Текст сообщения", style=discord.ButtonStyle.secondary, row=0)
    async def content_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_modal(ContentModal(self))

    @ui.button(label="🖼️ Изображение", style=discord.ButtonStyle.secondary, row=2)
    async def image_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_message(
            "Выберите источник изображения:",
            view=ImageActionView(self, "image"),
            ephemeral=True,
        )

    @ui.button(label="📌 Превью", style=discord.ButtonStyle.secondary, row=2)
    async def thumbnail_button(self, i: discord.Interaction, _: ui.Button) -> None:
        await i.response.send_message(
            "Выберите источник миниатюры:",
            view=ImageActionView(self, "thumbnail"),
            ephemeral=True,
        )

    @ui.button(label="[+] Добавить поле", style=discord.ButtonStyle.success, row=3)
    async def add_field_button(self, i: discord.Interaction, _: ui.Button) -> None:
        if len(self.embed.fields) >= 25:
            await i.response.send_message("❌ Лимит 25 полей.", ephemeral=True)
            return
        await i.response.send_modal(FieldModal(self))

    @ui.button(label="✏️ Изменить/Удалить", style=discord.ButtonStyle.primary, row=3)
    async def edit_delete_field_button(
        self, i: discord.Interaction, _: ui.Button
    ) -> None:
        if not self.embed.fields:
            await i.response.send_message("Нет полей.", ephemeral=True)
            return
        edit_view = ui.View(timeout=180)
        edit_view.add_item(FieldSelect(self))
        await i.response.send_message("Выберите поле:", view=edit_view, ephemeral=True)

    @ui.button(label="⇅ Порядок полей", style=discord.ButtonStyle.secondary, row=3)
    async def reorder_fields_button(self, i: discord.Interaction, _: ui.Button) -> None:
        if len(self.embed.fields) < 2:
            await i.response.send_message("Нужно минимум 2 поля.", ephemeral=True)
            return
        await i.response.send_message(
            "Что и куда переместить:", view=ReorderFieldsView(self), ephemeral=True
        )

    @ui.button(label="➖ Разделитель", style=discord.ButtonStyle.secondary, row=3)
    async def add_separator_button(self, i: discord.Interaction, _: ui.Button) -> None:
        if len(self.embed.fields) >= 25:
            await i.response.send_message("❌ Лимит 25 полей.", ephemeral=True)
            return
        self.embed.add_field(name="​", value="​", inline=False)
        await i.response.defer()
        await self.update_preview()

    @ui.button(label="✅ Опубликовать", style=discord.ButtonStyle.success, row=4)
    async def publish_button(self, i: discord.Interaction, _: ui.Button) -> None:
        final_embed = self.embed.copy()
        if final_embed.description:
            final_embed.description = parse_text_colors(final_embed.description)
        for idx, field in enumerate(final_embed.fields):
            final_embed.set_field_at(
                idx,
                name=field.name,
                value=parse_text_colors(field.value),
                inline=field.inline,
            )

        mention = self.role_to_mention.mention if self.role_to_mention else ""
        content = f"{mention} {self.message_content or ''}".strip()
        await self.target_channel.send(
            content=content or None,
            embed=final_embed,
            allowed_mentions=_PUBLISH_MENTIONS,
        )
        self.clear_items()
        await i.response.edit_message(
            content="✅ **Анонс опубликован!**", view=None, embed=None
        )
        self.stop()

    @ui.button(label="❌ Отменить", style=discord.ButtonStyle.danger, row=4)
    async def cancel_button(self, i: discord.Interaction, _: ui.Button) -> None:
        self.clear_items()
        await i.response.edit_message(
            content="❌ Конструктор закрыт.", view=None, embed=None
        )
        self.stop()


# =================================================================== #
#  4. Command
# =================================================================== #
class Builder(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="constructor", description="Интерактивный конструктор анонсов"
    )
    @app_commands.describe(
        channel="Канал для публикации",
        mention_role="Роль для упоминания при публикации",
    )
    @can_announce()
    async def constructor(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        mention_role: Optional[discord.Role] = None,
    ) -> None:
        view = GigaBuilderView(interaction.user, channel, mention_role, self.bot)
        await interaction.response.send_message(
            "**🚀 Конструктор анонсов запущен!**\nИспользуйте кнопки ниже. "
            "Предпросмотр обновляется в реальном времени.",
            embed=view.embed,
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Builder(bot))
