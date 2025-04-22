import discord
import os

MUSIC_FOLDER = './music'
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True
MAX_TRACK_LENGTH = 1200
ALLOW_PLAYLISTS = False
ANNOUNCE = {
    "ALLOWED_ROLES": list(map(int, os.getenv("ALLOWED_ROLES").split(','))) if os.getenv("ALLOWED_ROLES") else [],
    "DEFAULT_CHANNEL": int(os.getenv("DEFAULT_CHANNEL")) if os.getenv("DEFAULT_CHANNEL") else None,
    "COLOR": 0x2b2d31
}