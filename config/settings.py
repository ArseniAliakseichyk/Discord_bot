import discord
import os
from dotenv import load_dotenv

load_dotenv()

MUSIC_FOLDER = './music'
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True
INTENTS.members = True
INTENTS.guilds = True
MAX_TRACK_LENGTH = 1200
ALLOW_PLAYLISTS = False
ANNOUNCE = {
    "ALLOWED_ROLES": list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else [],
    "DEFAULT_CHANNEL": int(os.getenv("DEFAULT_CHANNEL")) if os.getenv("DEFAULT_CHANNEL") else None,
    "COLOR": 0x2b2d31
}

try:
    VERIFY_ROLE_ID = int(os.getenv("VERIFY_ROLE_ID"))
except (TypeError, ValueError):
    print("Ошибка: VERIFY_ROLE_ID не найден или не является числом в .env файле.")
    VERIFY_ROLE_ID = None

try:
    SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID"))
except (TypeError, ValueError):
    print("Ошибка: SUPPORT_ROLE_ID не найден или не является числом в .env файле.")
    SUPPORT_ROLE_ID = None

try:
    TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID"))
except (TypeError, ValueError):
    print("Ошибка: TICKET_CATEGORY_ID не найден или не является числом в .env файле.")
    TICKET_CATEGORY_ID = None

try:
    CREATOR_ID = int(os.getenv('CREATOR_ID'))
    ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID'))
    MODERATOR_ROLE_ID = int(os.getenv('MODERATOR_ROLE_ID'))
    GUILD_ID = int(os.getenv('GUILD_ID'))
except (TypeError, ValueError):
    print("Ошибка: ID для CREATOR, ADMIN, MODERATOR или GUILD не найдены в .env файле.")
    CREATOR_ID = None
    ADMIN_ROLE_ID = None
    MODERATOR_ROLE_ID = None
    GUILD_ID = None