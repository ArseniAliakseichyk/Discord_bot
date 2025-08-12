import discord
from discord import app_commands

@app_commands.command(name="help", description="Показать список команд")
async def help_command(interaction: discord.Interaction):
    """Показывает список всех доступных команд"""
    embed = discord.Embed(
        title="🎵 Доступные команды",
        color=0x2b2d31
    )
    
    music_cmds = (
        "**/play** - Воспроизвести трек\n"
        "**/now** - Текущий трек\n"
        "**/queue** - Показать очередь\n"
        "**/shuffle** - Перемешать очередь\n"
        "**/clear** - Очистить очередь"
    )
    
    utility_cmds = (
        "**/join** - Подключиться к голосовому\n"
        "**/jointo** - Подключиться к конкретному каналу\n"
        "**/leave** - Отключиться\n"
        "**/announce** - Сделать объявление"
    )
    
    embed.add_field(name="🎶 Музыка", value=music_cmds, inline=False)
    embed.add_field(name="⚙️ Утилиты", value=utility_cmds, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)