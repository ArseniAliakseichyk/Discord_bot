# Discord Music Bot

A Discord music bot built with Discord.py that plays music from YouTube or local files in voice channels. It supports queue management, playback controls via interactive buttons, and utility commands for voice channel management and announcements.

## Features
- **Music Playback**: Play tracks from YouTube (via links or search queries) or local files stored in the music folder.
- **Queue Management**: Add, view, shuffle, or clear the song queue.
- **Interactive Controls**: Use buttons for play, pause, resume, skip, stop, and toggle looping of the current track.
- **Voice Channel Management**: Join or leave voice channels, or connect to specific channels with permissions.
- **Announcements**: Send official announcements to specified channels with role mentions (admin/moderator only).
- **Error Handling**: Robust handling for age-restricted YouTube videos, invalid links, and connection issues.
- **Local File Support**: Play audio files stored in the configured music folder.
- **Dynamic Status Updates**: Real-time updates of the "Now Playing" embed with track progress and status.

## Installation

### Prerequisites
1. **Python 3.8+**: Ensure Python is installed.
2. **FFmpeg**: Install FFmpeg and add it to your system's PATH.
3. **Discord Bot Token**: Create a bot on the [Discord Developer Portal](https://discord.com/developers/applications) and obtain its token.

### Steps
1. **Clone the Repository**:
    ```bash
    git clone https://github.com/ArseniAliakseichyk/Discord_bot_music.git
    cd Discord_bot_music
    ```

2. **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory with the following:
    ```
    DISCORD_TOKEN=your-discord-bot-token
    ALLOWED_ROLES=admin-role-id,moderator-role-id
    DEFAULT_CHANNEL=announcements-channel-id
    ```
   - `DISCORD_TOKEN`: Your bot's token from the Discord Developer Portal.
   - `ALLOWED_ROLES`: Comma-separated list of role IDs allowed to use restricted commands (e.g., `/announce`, `/jointo`).
   - `DEFAULT_CHANNEL`: ID of the default channel for announcements.

4. **Set Up Music Folder**:
   Create a `music` folder in the root directory to store local audio files (configured in `config/settings.py`).

5. **Run the Bot**:
    ```bash
    python bot.py
    ```

### Requirements
The bot uses the following Python packages (listed in `requirements.txt`):
- `discord.py>=2.3.2`: For Discord API interaction.
- `yt-dlp>=2023.7.6`: For fetching YouTube audio streams.
- `python-dotenv>=1.0.0`: For loading `.env` variables.
- `ffmpeg-python>=0.2.0`: For audio processing with FFmpeg.
- `cachetools>=5.3.1`: For caching YouTube metadata.
- `tenacity>=8.2.3`: For retrying failed operations.
- `PyNaCl>=1.5.0`: For voice channel audio encryption.

Install them with:
```bash
pip install -r requirements.txt
```

## Directory Structure
- **`bot.py`**: Main bot script that initializes the bot, loads environment variables, and handles events like `on_ready` and `on_voice_state_update`.
- **`commands/`**:
  - **`music/`**: Music-related commands (`/play`, `/now`, `/queue`, `/shuffle`, `/clear`).
  - **`utility/`**: Voice and admin commands (`/join`, `/leave`, `/jointo`, `/announce`).
  - **`register.py`**: Registers slash commands with Discord.
- **`config/`**:
  - **`settings.py`**: Bot configuration (intents, music folder, announcement settings).
- **`core/`**:
  - **`player.py`**: Handles audio playback and track processing.
  - **`queue_manager.py`**: Manages the song queue and processes track requests.
  - **`state.py`**: Tracks playback state (queue, current track, looping, etc.).
  - **`voice.py`**: Manages voice channel connections.
- **`ui/`**:
  - **`controls.py`**: Defines interactive buttons for playback control.
- **`utils/`**:
  - **`yt_utils.py`**: Utilities for fetching YouTube metadata using `yt-dlp`.
- **`.gitignore`**: Ignores `.env`, `__pycache__`, and other temporary files.
- **`requirements.txt`**: Lists Python dependencies.

## Commands
All commands are slash commands (`/` prefix). Below is a list of available commands:

### Music Commands
- **`/play <query>`**: Play a track from a YouTube link, search query, or local file name. Playlists are disabled.
- **`/now`**: Display the currently playing track with details (title, duration, progress, source, status).
- **`/queue`**: Show the current song queue.
- **`/shuffle`**: Randomly shuffle the queue.
- **`/clear`**: Clear the song queue.

### Voice Commands
- **`/join`**: Connect the bot to the user's voice channel.
- **`/leave`**: Disconnect the bot from the voice channel and clear the queue.
- **`/jointo <channel>`**: Connect the bot to a specific voice channel by name or ID (requires admin or allowed role).

### Utility Commands
- **`/announce <message> [channel] [mention_role]`**: Send an official announcement to a specified or default channel with an optional role mention (requires admin or allowed role).

### Interactive Buttons
Available on the "Now Playing" embed:
- **⏸️ Pause**: Pause the current track.
- **▶️ Resume**: Resume a paused track.
- **⏭️ Skip**: Skip to the next track in the queue.
- **⏹️ Stop**: Stop playback and clear the queue.
- **🔄 Loop**: Toggle looping of the current track (commented out in current code but can be enabled).

## Configuration
- **Music Folder**: Set in `config/settings.py` (`MUSIC_FOLDER='./music'`). Place local audio files here.
- **Intents**: Configured in `config/settings.py` to enable message content and voice state updates.
- **Announcement Settings**: Defined in `config/settings.py` (`ANNOUNCE` dictionary) for default channel and embed color.
- **Environment Variables**: Set in `.env` for token, allowed roles, and default announcement channel.

## License
This project is licensed under the MIT License.