import discord
from discord import app_commands, ui

def create_main_embed() -> discord.Embed:
    """Создает главный Embed для страницы приветствия."""
    embed = discord.Embed(
        title="👋 Помощь по боту",
        description=(
            "Привет! Я многофункциональный бот, созданный для управления музыкой "
            "и создания продвинутых постов на вашем сервере.\n\n"
            "Я могу проигрывать музыку с **YouTube** (по ссылкам или поиску) и **Spotify**. "
            "Воспроизведение плейлистов YouTube отключено."
        ),
        color=0x2b2d31
    )
    embed.add_field(
        name="🎵 Музыка",
        value="Все команды для управления воспроизведением, очередью и информацией о треках.",
        inline=False
    )
    embed.add_field(
        name="⚙️ Утилиты",
        value="Команды для управления голосовыми каналами и создания простых объявлений.",
        inline=False
    )
    embed.add_field(
        name="🛠️ Конструктор (Admin)",
        value="Мощный визуальный редактор для создания и отправки сложных Embed-сообщений (постов).",
        inline=False
    )
    embed.set_footer(text="Выберите категорию из меню ниже, чтобы узнать больше.")
    return embed

def create_music_embed() -> discord.Embed:
    """Создает Embed для музыкальных команд."""
    embed = discord.Embed(
        title="🎵 Музыкальные Команды",
        description="Управляйте воспроизведением в голосовом канале.",
        color=0x5865F2
    )
    embed.add_field(name="/play [запрос]", value="Воспроизвести трек с YouTube (ссылка/поиск) или Spotify.", inline=False)
    embed.add_field(name="/now", value="Показать подробную информацию о текущем треке, включая прогресс.", inline=False)
    embed.add_field(name="/queue", value="Показать список следующих треков в очереди.", inline=False)
    embed.add_field(name="/shuffle", value="Перемешать очередь в случайном порядке.", inline=False)
    embed.add_field(name="/clear", value="Полностью очистить очередь воспроизведения.", inline=False)
    
    embed.add_field(
        name="▶️ Интерактивные Кнопки",
        value=(
            "На сообщении 'Сейчас играет' доступны кнопки для:\n"
            "• **⏸️ Пауза**\n"
            "• **▶️ Продолжить**\n"
            "• **⏭️ Скип** (пропустить трек)\n"
            "• **⏹️ Стоп** (остановить и очистить очередь)"
        ),
        inline=False
    )
    return embed

def create_utility_embed() -> discord.Embed:
    """Создает Embed для команд утилит."""
    embed = discord.Embed(
        title="⚙️ Команды Утилит",
        description="Полезные команды для управления каналом и объявлений.",
        color=0x57F287
    )
    embed.add_field(name="/join", value="Подключиться к вашему текущему голосовому каналу.", inline=False)
    embed.add_field(name="/leave", value="Отключиться от голосового канала и очистить очередь.", inline=False)
    embed.add_field(name="/help", value="Показать это интерактивное меню помощи.", inline=False)
    
    embed.add_field(
        name="--- Админ-команды ---",
        value="*Для этих команд требуются права администратора или специальная роль.*",
        inline=False
    )
    embed.add_field(
        name="/jointo [канал]",
        value="`Admin/Role` Подключиться к *конкретному* голосовому каналу по имени или ID.",
        inline=False
    )
    embed.add_field(
        name="/announce [...]",
        value=(
            "`Admin/Role` Создать и отправить объявление.\n"
            "• Открывает модальное окно для ввода текста.\n"
            "• Позволяет упомянуть роль, добавить картинку, иконку и цвет.\n"
            "• Показывает предпросмотр перед отправкой."
        ),
        inline=False
    )
    return embed

def create_constructor_embed() -> discord.Embed:
    """Создает Embed для команды /constructor."""
    embed = discord.Embed(
        title="🛠️ Гига-Конструктор /constructor (Admin/Role)",
        description=(
            "Это самый мощный инструмент бота. Он представляет собой "
            "визуальный конструктор для создания сложных постов (Embeds) "
            "с помощью интерактивной панели и модальных окон.\n\n"
            "*Требует прав администратора или специальной роли.*"
        ),
        color=0xFEE75C
    )
    embed.add_field(
        name="Возможности Конструктора",
        value=(
            "• 💬 **Текст сообщения:** Добавить текст *над* постом (для @упоминаний).\n"
            "• 📝 **Основное:** Настроить Заголовок, Описание, URL и Цвет (вручную или из пресетов).\n"
            "• ✍️ **Автор:** Установить блок автора с иконкой и URL.\n"
            "• 🦶 **Футер:** Установить нижний колонтитул (футер) с иконкой.\n"
            "• 🖼️ **Изображения:** Добавить большое изображение *и/или* миниатюру (справа).\n"
            "• 📤 **Источник:** Загрузить картинки с ПК или вставить по URL.\n"
            "• ➕ **Поля (Fields):** Добавить до 25 полей (блоков текста).\n"
            "• ✏️ **Редактирование:** Изменять или удалять существующие поля.\n"
            "• ⇅ **Порядок:** Менять порядок полей."
        ),
        inline=False
    )
    return embed

class HelpView(ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.add_item(self.HelpSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяет, что с меню взаимодействует тот же юзер, что вызвал /help."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Вы не можете управлять этим меню.", ephemeral=True)
            return False
        return True

    class HelpSelect(ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(
                    label="Главная",
                    description="Общая информация о боте.",
                    emoji="👋",
                    value="main"
                ),
                discord.SelectOption(
                    label="Музыка",
                    description="Команды для управления музыкой.",
                    emoji="🎵",
                    value="music"
                ),
                discord.SelectOption(
                    label="Утилиты",
                    description="Полезные команды (join, announce).",
                    emoji="⚙️",
                    value="utility"
                ),
                discord.SelectOption(
                    label="Конструктор (Admin)",
                    description="Продвинутый редактор постов.",
                    emoji="🛠️",
                    value="constructor"
                ),
            ]
            super().__init__(
                placeholder="Выберите категорию для просмотра...",
                min_values=1,
                max_values=1,
                options=options
            )

        async def callback(self, interaction: discord.Interaction):
            """Вызывается при выборе опции в меню."""
            selection = self.values[0]
            embed = None

            if selection == "music":
                embed = create_music_embed()
            elif selection == "utility":
                embed = create_utility_embed()
            elif selection == "constructor":
                embed = create_constructor_embed()
            else:
                embed = create_main_embed()

            await interaction.response.edit_message(embed=embed)


@app_commands.command(name="help", description="Показать интерактивный список команд")
async def help_command(interaction: discord.Interaction):
    """Показывает интерактивное меню помощи."""
    
    embed = create_main_embed()
    
    view = HelpView(author_id=interaction.user.id)
    
    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )