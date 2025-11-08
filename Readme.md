# AstraBot: Music, Tickets & Admin Tools

🎵 🎫 🛠️

AstraBot is a comprehensive, all-in-one solution designed to manage a Discord community with powerful music playback, a robust ticket system, and advanced administrative tools. Built with Discord.py, it integrates seamlessly into your server using slash commands and persistent UI components.

## ✨ Key Features

* **🎧 High-Quality Music:** Play tracks, search YouTube, use Spotify links, and manage queues with an interactive "Now Playing" interface.
* **🎫 Interactive Ticket System:** A professional ticket workflow, from creation via a modal to a private, claimed channel for support staff.
* **✅ Role-Based Verification:** A persistent "Agree to Rules" button that automatically grants a verification role.
* **🛠️ Advanced Admin Tools:** Includes a powerful modal-based `/announce` command with previews and a modular `/constructor` for building complex embeds visually.
* **🔒 Permission Controlled:** Features are protected by role IDs (`ALLOWED_ROLES`, `SUPPORT_ROLE_ID`) defined in your config.

---

## Command Showcase

AstraBot's features are split into logical modules, all accessible via slash commands.

### 🎵 Music Module

Bring high-fidelity music to your voice channels.

* `/play <query>`: Plays music from a YouTube URL, search query, Spotify link (converts to YT search), or local file name.
* `/now`: Displays the currently playing track with a progress bar and details.
* `/queue`: Shows the list of upcoming songs.
* `/shuffle`: Randomizes the current queue.
* `/clear`: Empties the music queue.
* `/join` / `/leave`: Standard voice channel commands.
* `/jointo <channel>`: (Admin) Forces the bot to join a specific voice channel.

**Interactive Controls:**
The `/now` command (and the message sent when a song starts) includes buttons for:
* **⏸️ Pause** / **▶️ Resume**
* **⏭️ Skip**
* **⏹️ Stop** (Stops playback and clears the queue)

### 🎫 Ticket & Verification System

A complete system for user verification and support, triggered from a single admin-posted message.

* `/send_rules`: (Role-Restricted) Posts the main rules embed and the persistent button view.

This message contains three buttons:

1.  **✅ Agree to Rules**
    * Grants the user the `VERIFY_ROLE_ID`.
    * Sends an ephemeral "Success" message.
    * Won't grant the role if the user already has it.

2.  **📨 Contact Admin**
    * Opens a modal (`TicketModal`) asking for a **Subject** and **Description**.
    * Creates a new, private text channel in the `TICKET_CATEGORY_ID`.
    * Pings the `SUPPORT_ROLE_ID` in the new channel.
    * The user who created the ticket **cannot** see the channel yet.

3.  **🤖 Bot Commands**
    * Instantly displays the interactive `/help` menu to the user (ephemeral).

**Ticket Workflow (For Staff):**
1.  A support staff member sees the new ticket and clicks **"Взять в работу" (Claim Ticket)**.
2.  The channel is renamed (e.g., `claimed-ticket-0001`).
3.  The user who created the ticket is **added** to the channel with `read_messages`, `send_messages`, and `read_message_history` permissions.
4.  The bot sends a message tagging the user and the staff member who claimed it.
5.  When the issue is resolved, staff clicks **"Закрыть тикет" (Close Ticket)**.
6.  The channel is renamed (e.g., `closed-ticket-0001`) and the user's permissions are revoked, hiding the channel from them.

### 🛠️ Admin & Utility Tools

Powerful tools for server management, restricted to `ALLOWED_ROLES`.

* `/help`: Displays a dynamic, interactive help menu showing all available commands.
* `/announce`: Opens a modal to create a beautiful, custom announcement. You can set a target channel, role to mention, image URL, and more. It even shows you a preview before sending!
* `/constructor`: A "Giga-Constructor" for visually building and sending extremely complex embeds. You can add/edit/reorder fields, set authors, footers, images, and text content, all from an interactive button panel.

---

## 🚀 Getting Started

Follow these steps to get AstraBot running on your own server.

### Prerequisites

* [Python 3.10+](https://www.python.org/downloads/)
* [FFmpeg](https://ffmpeg.org/download.html) (Must be added to your system's PATH for music playback)
* [Git](https://git-scm.com/downloads) (Recommended)

### 1. Clone the Repository

```bash
git clone [https://github.com/your-username/AstraBot.git](https://github.com/your-username/AstraBot.git)
cd AstraBot
```

### 2. Install Dependencies

It's highly recommended to use a virtual environment.

```bash
# Create a virtual environment (Windows)
python -m venv venv
.env\Scriptsctivate

# Create a virtual environment (Linux/macOS)
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

**Key Libraries:**

* discord.py>=2.3.2
* yt-dlp (For YouTube/Spotify playback)
* python-dotenv (For managing your .env file)
* requests
* PyNaCl (For voice)

### 3. Configuration (.env)

This is the most important step. Create a file named `.env` in the root of the project. Copy and paste the template below and fill in all the required IDs.

To get IDs: Enable Developer Mode in Discord, then right-click on a user, role, channel, or server and select "Copy ID".

```ini
# ---------------------------------
# CORE BOT CONFIG
# ---------------------------------

DISCORD_TOKEN=your_bot_token_here
LOG_CHANNEL_ID=your_log_channel_id_here

# ---------------------------------
# ADMIN & UTILITY CONFIG
# ---------------------------------

ALLOWED_ROLES=role_id_1,role_id_2
DEFAULT_CHANNEL=default_announcement_channel_id_here
EXCLUDED_USER_IDS=user_id_1,user_id_2

# ---------------------------------
# TICKET & VERIFICATION SYSTEM
# ---------------------------------

VERIFY_ROLE_ID=role_id_for_verified_members
TICKET_CATEGORY_ID=category_id_for_tickets
SUPPORT_ROLE_ID=role_id_for_support_staff

# ---------------------------------
# RULES EMBED CONFIG
# ---------------------------------
GUILD_ID=your_server_id_here
CREATOR_ID=user_id_of_creator
ADMIN_ROLE_ID=your_admin_role_id
MODERATOR_ROLE_ID=your_moderator_role_id
```

### 4. Run the Bot

```bash
python bot.py
```

The bot will connect, log its startup, and be ready to use.

---

## 📁 Project Structure

```
/AstraBot
|-- .env
|-- .gitignore
|-- bot.py
|-- requirements.txt
|-- ticket_counter.txt
|-- [commands]
|-- [config]
|-- [core]
|-- [cogs]
|-- [ui]
|-- [utils]
```

## 📄 License

This project is licensed under the MIT License.
