
# Discord Music Bot

This repository is a simple Discord music bot that allows users to play music from YouTube directly in a voice channel, manage a queue, and control playback with interactive buttons. It uses the Discord.py library and yt-dlp for fetching and playing YouTube audio.

## Features
- **Play music**: Play songs from YouTube by providing a search query or YouTube link.
- **Queue management**: View, clear, shuffle, and control the queue.
- **Voice controls**: Play, pause, resume, skip, and stop music playback.
- **Looping**: Enable or disable looping of the current track.
- **Interactive buttons**: Provide easy interaction with buttons like play, pause, resume, stop, and loop.

## Installation

### Prerequisites
1. **Python 3.8+**  
2. **FFmpeg**: Ensure FFmpeg is installed and available in your system's PATH.

### Steps
1. Clone the repository:
    ```bash
    git clone https://github.com/ArseniAliakseichyk/Discord_bot_music.git
    cd Discord_bot_music
    ```

2. Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3. Create a `.env` file in the root directory with your bot's token:
    ```
    DISCORD_TOKEN=your-discord-bot-token
    ```

4. Run the bot:
    ```bash
    python bot.py
    ```

### Requirements
The bot uses the following Python packages:
- `discord.py`: For interacting with Discord's API.
- `yt-dlp`: For extracting audio from YouTube.
- `python-dotenv`: For loading environment variables from `.env` files.
- `ffmpeg-python`: For handling audio processing with FFmpeg.

Ensure all dependencies are installed by running:
```bash
pip install -r requirements.txt
```

## Directory Structure
Here is a brief explanation of the key directories and files:

- **`bot.py`**: Main entry point of the bot that loads the necessary environment variables and starts the bot.
- **`commands/`**: Directory for bot commands such as playing music, managing the queue, and voice channel commands.
    - **`music/`**: Commands related to playing and managing music.
    - **`utility/`**: Commands related to voice channel management (joining and leaving).
    - **`register.py`**: Registers the commands with Discord’s slash command interface.
- **`config/`**: Configuration files.
    - **`settings.py`**: Contains bot configuration like music folder and intents.
- **`core/`**: Contains the core logic of the bot.
    - **`state.py`**: Tracks the current state of the queue, looping, and currently playing track.
    - **`voice.py`**: Handles voice channel connection and disconnection.
    - **`player.py`**: Handles the actual playback of music.
- **`ui/`**: Contains Discord UI elements, such as control buttons for play, pause, skip, and loop.
- **`utils/`**: Helper utilities, including fetching YouTube info.

## Commands
The bot supports the following commands:

- `/play <query>`: Play a song or playlist from YouTube.
- `/now`: Show the current playing track.
- `/queue`: View the current song queue.
- `/shuffle`: Shuffle the queue.
- `/clear`: Clear the song queue.
- `/join`: Join the user's voice channel.
- `/leave`: Leave the voice channel and clear the queue.

### Interactive Buttons:
- **Pause**: Pause the currently playing song.
- **Resume**: Resume a paused song.
- **Skip**: Skip the current song and play the next one in the queue.
- **Stop**: Stop the music and clear the queue.
- **Loop**: Toggle looping the current song.

## Configuration
- **MUSIC_FOLDER**: Define the folder where local music files are stored (in `config/settings.py`).
- **DISCORD_TOKEN**: Your Discord bot token (in `.env`).

## Troubleshooting
- **FFmpeg not found**: Ensure that FFmpeg is correctly installed and added to your system’s PATH.
- **YouTube links not working**: Make sure yt-dlp is up-to-date and can fetch information from YouTube.

## License
This project is licensed under the MIT License.