import discord

MUSIC_FOLDER = './music'
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True
MAX_TRACK_LENGTH = 1200
ALLOW_PLAYLISTS = False