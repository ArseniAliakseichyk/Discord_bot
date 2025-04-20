import discord

MUSIC_FOLDER = './music'
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True
MAX_TRACK_LENGTH = 1200
ALLOW_PLAYLISTS = False
ANNOUNCE = {
    "ALLOWED_ROLES": ["", ""], #id Admins , Moders
    "DEFAULT_CHANNEL": "", #chat id
    "COLOR": 0x2b2d31
}