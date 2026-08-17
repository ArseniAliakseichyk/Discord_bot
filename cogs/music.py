"""Music commands backed by Lavalink via wavelink.

Per-guild state lives on the wavelink ``Player`` (one per guild) and its
``player.queue`` — there is no global state.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.constants import (
    MSG_BOT_NOT_CONNECTED,
    MSG_JOIN_VOICE_FIRST,
    MSG_NOTHING_PLAYING,
    MSG_QUEUE_EMPTY,
)
from core.db import PlayerSession, SavedTrack
from ui.controls import now_playing_panel
from ui.search import SearchView
from ui.v2 import PanelView, make_panel
from utils.checks import guild_authorized, has_dj, in_command_channel
from utils.formatting import format_duration, format_ms, parse_position
from utils.player import connect_and_configure, player_of

logger = logging.getLogger("bot.music")

SEARCH_RESULTS = 5
QUEUE_PAGE = 20
#: Discord shows at most 25 autocomplete choices, each name up to 100 chars.
AUTOCOMPLETE_LIMIT = 25
AUTOCOMPLETE_LABEL_LIMIT = 100

LOOP_MODES = {
    "off": wavelink.QueueMode.normal,
    "track": wavelink.QueueMode.loop,
    "queue": wavelink.QueueMode.loop_all,
}
LOOP_REPLIES = {
    "off": "➡️ Повтор выключен.",
    "track": "🔂 Повтор текущего трека.",
    "queue": "🔁 Повтор всей очереди.",
}

#: Search prefixes understood by Lavalink and its plugins. A query that already
#: starts with one must be passed through untouched: wavelink only skips adding
#: its own prefix for URLs, so ``spsearch:foo`` would otherwise be sent as
#: ``ytsearch:spsearch:foo`` and match nothing.
SOURCE_PREFIXES = (
    "ytsearch:",
    "ytmsearch:",
    "scsearch:",
    "spsearch:",
    "sprec:",
    "dzsearch:",
    "dzisrc:",
    "amsearch:",
    "local:",
)

#: Hosts served by the LavaSrc Spotify source.
SPOTIFY_HOSTS = ("open.spotify.com", "play.spotify.com", "spotify.link")

#: Spotify link kinds whose contents cannot be listed by a bot.
#:
#: Both were verified against the live Web API, and both come from Spotify's
#: February 2026 Developer Mode migration rather than from this bot:
#:
#: * albums — LavaSrc hydrates them through ``GET /v1/tracks?ids=``, which
#:   Spotify **removed** in that migration, so the call answers 403. A future
#:   LavaSrc release could switch to ``/v1/albums/{id}/tracks``, which still
#:   works, so this one may start working again on its own.
#: * playlists — ``GET /v1/playlists/{id}/items`` now answers 401 "valid user
#:   authentication required": it needs a logged-in user, which a
#:   client-credentials bot does not have.
SPOTIFY_BULK_PATHS = ("/album/", "/playlist/")

MSG_SPOTIFY_DISABLED = (
    "⚠️ Spotify не настроен на этом сервере.\n"
    "Владельцу бота нужно задать `SPOTIFY_CLIENT_ID` и `SPOTIFY_CLIENT_SECRET` "
    "и перезапустить Lavalink."
)

MSG_SPOTIFY_BULK = (
    "⚠️ Альбомы и плейлисты Spotify не открываются.\n"
    "Spotify закрыл доступ к их составу для ботов в обновлении Web API "
    "(февраль 2026) — это ограничение на его стороне, не в боте.\n\n"
    "**Что работает:** ссылка на отдельный трек Spotify, поиск "
    "`spsearch: название`, плейлисты и альбомы **YouTube**."
)


class SpotifyNotConfigured(Exception):
    """A Spotify query arrived but the LavaSrc credentials are absent."""


class SpotifyBulkUnsupported(Exception):
    """A Spotify album/playlist link arrived; Spotify will not serve its items."""


class Music(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        # Per-guild now-playing message and the channel where commands were used.
        self.now_messages: dict[int, discord.Message] = {}
        self.home_channels: dict[int, int] = {}
        self._restored = False
        # Guilds currently being torn down by stop_player: the forced skip fires
        # on_wavelink_track_end, which would otherwise re-save the session we are
        # about to delete.
        self._stopping: set[int] = set()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    async def ensure_player(
        self, interaction: discord.Interaction
    ) -> wavelink.Player | None:
        """Return the guild player, connecting to the user's channel if needed."""
        player = player_of(interaction.guild)
        if player is not None:
            return player
        user = interaction.user
        if (
            not isinstance(user, discord.Member)
            or user.voice is None
            or user.voice.channel is None
        ):
            return None
        return await connect_and_configure(user.voice.channel, self.bot)

    @staticmethod
    def _set_requester(track: wavelink.Playable, member: discord.Member) -> None:
        track.extras = {
            "requester": member.display_name,
            "avatar": member.display_avatar.url,
        }

    def _track_too_long(self, track: wavelink.Playable) -> bool:
        max_seconds = self.bot.settings.max_track_length
        if max_seconds <= 0 or track.is_stream or not track.length:
            return False
        return track.length / 1000 > max_seconds

    def _local_file(self, query: str) -> str | None:
        """Map ``query`` to a path inside the Lavalink music volume, if it is one.

        The query comes straight from a user, so the resolved path must be
        confined to ``music_folder``: without the containment check a query like
        ``../../etc/passwd`` would escape it.
        """
        base = Path(self.bot.settings.music_folder).resolve()
        try:
            candidate = (base / query).resolve()
            relative = candidate.relative_to(base)
        except (ValueError, OSError):  # outside the base, or an unusable path
            return None
        if not candidate.is_file():
            return None
        container_dir = self.bot.settings.lavalink_local_dir.rstrip("/")
        return f"{container_dir}/{relative.as_posix()}"

    @staticmethod
    def _is_spotify(query: str) -> bool:
        lowered = query.lower()
        if lowered.startswith(("spsearch:", "sprec:")):
            return True
        return any(host in lowered for host in SPOTIFY_HOSTS)

    @classmethod
    def _is_spotify_bulk(cls, query: str) -> bool:
        """A Spotify album or playlist link, whose contents Spotify withholds."""
        lowered = query.lower()
        return cls._is_spotify(lowered) and any(
            part in lowered for part in SPOTIFY_BULK_PATHS
        )

    async def _resolve(self, query: str) -> wavelink.Search:
        """Turn a user query into tracks.

        Order matters: a local file wins over anything else, then an explicit
        source prefix is honoured as given, and only a bare query falls back to
        a YouTube search. Spotify links need no special handling beyond the
        credential check — Lavalink's LavaSrc source manager claims the URL, and
        wavelink never prefixes a URL.
        """
        if self._is_spotify(query):
            if not self.bot.settings.spotify_enabled:
                raise SpotifyNotConfigured
            if self._is_spotify_bulk(query):
                # Fail fast with an explanation rather than letting LavaSrc hit
                # the endpoint Spotify refuses and surface "nothing found".
                raise SpotifyBulkUnsupported

        # is_file() hits the filesystem; keep the blocking syscall off the loop.
        local_path = await asyncio.to_thread(self._local_file, query)
        if local_path is not None:
            return await wavelink.Playable.search(local_path)

        if query.lower().startswith(SOURCE_PREFIXES):
            # source=None: the caller already chose the source.
            return await wavelink.Playable.search(query, source=None)

        return await wavelink.Playable.search(
            query, source=wavelink.TrackSource.YouTube
        )

    async def maybe_start(self, player: wavelink.Player) -> None:
        if not player.playing and not player.queue.is_empty:
            await player.play(player.queue.get())

    @staticmethod
    def _to_saved(track: wavelink.Playable) -> SavedTrack:
        extras = getattr(track, "extras", None)
        return SavedTrack(
            uri=track.uri or "",
            requester=getattr(extras, "requester", None) if extras else None,
            avatar=getattr(extras, "avatar", None) if extras else None,
        )

    async def persist_queue(self, player: wavelink.Player) -> None:
        if player.guild is None or player.channel is None:
            return
        if player.guild.id in self._stopping:
            return  # teardown in progress; the session row is being deleted
        tracks: list[SavedTrack] = []
        if player.current is not None and player.current.uri:
            tracks.append(self._to_saved(player.current))
        tracks.extend(self._to_saved(t) for t in player.queue if t.uri)
        text_channel_id = self.home_channels.get(player.guild.id)
        try:
            await self.bot.db.save_session(
                player.guild.id, player.channel.id, text_channel_id, tracks
            )
        except sqlite3.Error:
            logger.exception("Failed to persist session")

    async def refresh_now_message(self, player: wavelink.Player) -> None:
        if player.guild is None:
            return
        message = self.now_messages.get(player.guild.id)
        if message is not None and player.current is not None:
            try:
                await message.edit(view=now_playing_panel(player.current, player, self))
            except discord.HTTPException:
                pass

    async def clear_now_message(self, guild_id: int) -> None:
        message = self.now_messages.pop(guild_id, None)
        if message is not None:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    def _forget_guild(self, guild_id: int) -> None:
        """Drop per-guild bookkeeping so the dicts don't grow without bound."""
        self.home_channels.pop(guild_id, None)
        self.now_messages.pop(guild_id, None)
        self._stopping.discard(guild_id)

    async def stop_player(self, player: wavelink.Player) -> None:
        if player.guild is None:
            return
        guild_id = player.guild.id
        self._stopping.add(guild_id)
        try:
            player.autoplay = wavelink.AutoPlayMode.partial
            player.queue.clear()
            player.auto_queue.clear()
            if player.playing or player.current is not None:
                await player.skip(force=True)
            await self.clear_now_message(guild_id)
            await self.bot.db.clear_session(guild_id)
        finally:
            self._stopping.discard(guild_id)

    async def add_and_play(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
        member: discord.Member,
    ) -> bool:
        """Enqueue a chosen track and start if idle. False if there is no player.

        The search menu relies on the return value: it must not report success
        when the requester has meanwhile left the voice channel.
        """
        player = await self.ensure_player(interaction)
        if player is None or interaction.guild is None:
            return False
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]
        self._set_requester(track, member)
        player.queue.put(track)
        await self.maybe_start(player)
        await self.persist_queue(player)
        return True

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="play",
        description="Воспроизвести трек или плейлист: YouTube, Spotify, локальный файл",
    )
    @app_commands.describe(
        query="Ссылка (YouTube/Spotify), поисковый запрос или имя локального файла"
    )
    # Decorators evaluate bottom-up, so the cooldown listed first runs last:
    # an unauthorized guild is rejected before the bucket is consumed.
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        if player is None or interaction.guild is None:
            await interaction.followup.send(MSG_JOIN_VOICE_FIRST)
            return
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]

        try:
            result = await self._resolve(query.strip())
        except SpotifyNotConfigured:
            await interaction.followup.send(MSG_SPOTIFY_DISABLED)
            return
        except SpotifyBulkUnsupported:
            await interaction.followup.send(MSG_SPOTIFY_BULK)
            return
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
            logger.warning("Search failed for %r", query, exc_info=True)
            await interaction.followup.send("⚠️ Не удалось найти трек.")
            return

        if not result:
            await interaction.followup.send("⚠️ По запросу ничего не найдено.")
            return

        if isinstance(result, wavelink.Playlist):
            tracks = [t for t in result.tracks if not self._track_too_long(t)]
            tracks = tracks[: self.bot.settings.max_playlist_tracks]
            if not tracks:
                await interaction.followup.send("⚠️ В плейлисте нет подходящих треков.")
                return
            for track in tracks:
                self._set_requester(track, interaction.user)  # type: ignore[arg-type]
                player.queue.put(track)
            await interaction.followup.send(
                f"🎵 Добавлен плейлист **{result.name}** — {len(tracks)} треков."
            )
        else:
            track = result[0]
            if self._track_too_long(track):
                limit = format_duration(self.bot.settings.max_track_length)
                await interaction.followup.send(f"⚠️ Трек длиннее лимита ({limit}).")
                return
            self._set_requester(track, interaction.user)  # type: ignore[arg-type]
            player.queue.put(track)
            await interaction.followup.send(f"🎵 Добавлен трек: **{track.title}**")

        await self.maybe_start(player)
        await self.persist_queue(player)

    @app_commands.command(name="search", description="Найти трек и выбрать из списка")
    @app_commands.describe(query="Поисковый запрос")
    # Decorators evaluate bottom-up, so the cooldown listed first runs last:
    # an unauthorized guild is rejected before the bucket is consumed.
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if (
            not isinstance(interaction.user, discord.Member)
            or interaction.user.voice is None
        ):
            await interaction.followup.send(MSG_JOIN_VOICE_FIRST)
            return
        try:
            result = await self._resolve(query.strip())
        except SpotifyNotConfigured:
            await interaction.followup.send(MSG_SPOTIFY_DISABLED)
            return
        except SpotifyBulkUnsupported:
            await interaction.followup.send(MSG_SPOTIFY_BULK)
            return
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
            logger.warning("Search failed for %r", query, exc_info=True)
            await interaction.followup.send("⚠️ Ошибка поиска.")
            return
        if isinstance(result, wavelink.Playlist):
            result = result.tracks
        if not result:
            await interaction.followup.send("⚠️ Ничего не найдено.")
            return
        tracks = list(result)[:SEARCH_RESULTS]
        view = SearchView(self, tracks, interaction.user)
        # No `content`: a Components V2 message cannot carry one — the heading
        # is part of the view itself.
        await interaction.followup.send(view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="now", description="Показать текущий трек")
    @guild_authorized()
    async def now(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is None or player.current is None:
            await interaction.response.send_message(
                MSG_NOTHING_PLAYING, ephemeral=True
            )
            return
        await interaction.response.send_message(
            view=now_playing_panel(player.current, player, self), ephemeral=True
        )

    @app_commands.command(name="queue", description="Показать очередь")
    @guild_authorized()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is None or (player.queue.is_empty and player.current is None):
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        lines: list[str] = []
        if player.current is not None:
            lines.append(f"▶️ **{player.current.title}**\n")
        for i, track in enumerate(player.queue, 1):
            if i > QUEUE_PAGE:
                lines.append(f"-# … и ещё {len(player.queue) - QUEUE_PAGE}")
                break
            lines.append(f"`{i:>2}.` {track.title}")

        total_ms = sum(t.length for t in player.queue if not t.is_stream and t.length)
        footer = [f"-# Треков в очереди: {len(player.queue)}"]
        if total_ms:
            footer.append(f"общая длительность {format_ms(total_ms)}")
        if player.queue.mode is not wavelink.QueueMode.normal:
            footer.append(
                "повтор трека"
                if player.queue.mode is wavelink.QueueMode.loop
                else "повтор очереди"
            )
        lines.append(" · ".join(footer))

        view = PanelView(timeout=None)
        view.add_item(make_panel(title="📜 Очередь", body="\n".join(lines)))
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="shuffle", description="Перемешать очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and not player.queue.is_empty:
            player.queue.shuffle()
            await self.persist_queue(player)
            await interaction.response.send_message("🔀 Очередь перемешана.")
        else:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)

    @app_commands.command(name="clear", description="Очистить очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def clear(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and not player.queue.is_empty:
            player.queue.clear()
            await self.persist_queue(player)
            await interaction.response.send_message("🧹 Очередь очищена.")
        else:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)

    async def _queue_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        """Offer queue entries by position, filtered by what has been typed."""
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            return []
        needle = current.strip().lower()
        choices: list[app_commands.Choice[int]] = []
        for index, track in enumerate(player.queue, 1):
            label = f"{index}. {track.title}"
            if needle and needle not in label.lower():
                continue
            choices.append(
                app_commands.Choice(name=label[:AUTOCOMPLETE_LABEL_LIMIT], value=index)
            )
            if len(choices) >= AUTOCOMPLETE_LIMIT:
                break
        return choices

    @app_commands.command(name="volume", description="Громкость текущего воспроизведения")
    @app_commands.describe(value="Громкость в процентах, 0..200")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def volume(
        self,
        interaction: discord.Interaction,
        value: app_commands.Range[int, 0, 200],
    ) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(
                MSG_BOT_NOT_CONNECTED, ephemeral=True
            )
            return
        try:
            await player.set_volume(value)
        except (wavelink.LavalinkException, wavelink.NodeException):
            logger.warning("Could not set the volume", exc_info=True)
            await interaction.response.send_message(
                "⚠️ Не удалось изменить громкость.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔊 Громкость: **{value}%** (только для текущей сессии — "
            "постоянное значение задаётся в `/settings volume`)."
        )

    @app_commands.command(name="seek", description="Перемотать текущий трек")
    @app_commands.describe(position="Позиция: 90, 1:30 или 1:02:03")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def seek(self, interaction: discord.Interaction, position: str) -> None:
        player = player_of(interaction.guild)
        if player is None or player.current is None:
            await interaction.response.send_message(
                MSG_NOTHING_PLAYING, ephemeral=True
            )
            return
        track = player.current
        if track.is_stream or not track.is_seekable:
            await interaction.response.send_message(
                "❌ Этот трек нельзя перематывать (прямой эфир).", ephemeral=True
            )
            return
        target = parse_position(position)
        if target is None:
            await interaction.response.send_message(
                "❌ Не понял позицию. Примеры: `90`, `1:30`, `1:02:03`.", ephemeral=True
            )
            return
        if track.length and target > track.length:
            await interaction.response.send_message(
                f"❌ Трек длится {format_ms(track.length)} — позиция за его пределами.",
                ephemeral=True,
            )
            return
        try:
            await player.seek(target)
        except (wavelink.LavalinkException, wavelink.NodeException):
            logger.warning("Seek failed", exc_info=True)
            await interaction.response.send_message(
                "⚠️ Не удалось перемотать.", ephemeral=True
            )
            return
        await self.refresh_now_message(player)
        await interaction.response.send_message(f"⏩ Перемотано на **{format_ms(target)}**.")

    @app_commands.command(name="loop", description="Режим повтора")
    @app_commands.describe(mode="Что повторять")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Выключить", value="off"),
            app_commands.Choice(name="Текущий трек", value="track"),
            app_commands.Choice(name="Всю очередь", value="queue"),
        ]
    )
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def loop(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(
                MSG_BOT_NOT_CONNECTED, ephemeral=True
            )
            return
        player.queue.mode = LOOP_MODES[mode.value]
        await self.refresh_now_message(player)
        await interaction.response.send_message(LOOP_REPLIES[mode.value])

    @app_commands.command(name="remove", description="Убрать трек из очереди")
    @app_commands.describe(position="Номер трека в очереди (см. /queue)")
    @app_commands.autocomplete(position=_queue_autocomplete)
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def remove(
        self, interaction: discord.Interaction, position: app_commands.Range[int, 1]
    ) -> None:
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        if position > len(player.queue):
            await interaction.response.send_message(
                f"❌ В очереди только {len(player.queue)} треков.", ephemeral=True
            )
            return
        index = position - 1  # the queue is 0-based, the command is 1-based
        title = player.queue.peek(index).title
        player.queue.delete(index)
        await self.persist_queue(player)
        await interaction.response.send_message(f"🗑️ Убрано из очереди: **{title}**")

    @app_commands.command(name="move", description="Переместить трек в очереди")
    @app_commands.describe(position="Какой трек переместить", to="На какую позицию")
    @app_commands.autocomplete(position=_queue_autocomplete)
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def move(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1],
        to: app_commands.Range[int, 1],
    ) -> None:
        player = player_of(interaction.guild)
        if player is None or player.queue.is_empty:
            await interaction.response.send_message(MSG_QUEUE_EMPTY, ephemeral=True)
            return
        size = len(player.queue)
        if position > size or to > size:
            await interaction.response.send_message(
                f"❌ В очереди только {size} треков.", ephemeral=True
            )
            return
        if position == to:
            await interaction.response.send_message(
                "ℹ️ Трек уже на этой позиции.", ephemeral=True
            )
            return
        # peek + delete rather than get_at: get_at also assigns the track to the
        # queue's `_loaded` slot, which is what QueueMode.loop replays — moving
        # a track would silently change what is on repeat.
        track = player.queue.peek(position - 1)
        player.queue.delete(position - 1)
        player.queue.put_at(to - 1, track)
        await self.persist_queue(player)
        await interaction.response.send_message(
            f"↕️ **{track.title}** — теперь на позиции **{to}**."
        )

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and (player.playing or player.current is not None):
            await player.skip(force=True)
            await interaction.response.send_message("⏭️ Пропущено.")
        else:
            await interaction.response.send_message(
                MSG_NOTHING_PLAYING, ephemeral=True
            )

    @app_commands.command(name="pause", description="Пауза")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and player.playing and not player.paused:
            await player.pause(True)
            await self.refresh_now_message(player)
            await interaction.response.send_message("⏸️ Пауза.")
        else:
            await interaction.response.send_message(
                "❌ Нечего ставить на паузу.", ephemeral=True
            )

    @app_commands.command(name="resume", description="Продолжить")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None and player.paused:
            await player.pause(False)
            await self.refresh_now_message(player)
            await interaction.response.send_message("▶️ Продолжаю.")
        else:
            await interaction.response.send_message(
                "❌ Воспроизведение не на паузе.", ephemeral=True
            )

    @app_commands.command(name="stop", description="Остановить и очистить очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = player_of(interaction.guild)
        if player is not None:
            await self.stop_player(player)
            await interaction.response.send_message(
                "⏹️ Воспроизведение остановлено, очередь очищена."
            )
        else:
            await interaction.response.send_message(
                MSG_BOT_NOT_CONNECTED, ephemeral=True
            )

    @app_commands.command(name="autoplay", description="Радио: автоплей похожих треков")
    @app_commands.describe(mode="Включить или выключить автоплей")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Включить (радио)", value="on"),
            app_commands.Choice(name="Выключить", value="off"),
        ]
    )
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def autoplay(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        player = player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(
                MSG_BOT_NOT_CONNECTED, ephemeral=True
            )
            return
        if mode.value == "on":
            player.autoplay = wavelink.AutoPlayMode.enabled
            await interaction.response.send_message("📻 Автоплей включён.")
        else:
            player.autoplay = wavelink.AutoPlayMode.partial
            await interaction.response.send_message("⏹️ Автоплей выключен.")

    # ------------------------------------------------------------------ #
    #  Wavelink events
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        player = payload.player
        if player is None or player.guild is None:
            return
        channel_id = self.home_channels.get(player.guild.id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.abc.Messageable):
            return
        await self.clear_now_message(player.guild.id)
        try:
            message = await channel.send(
                view=now_playing_panel(payload.track, player, self)
            )
            self.now_messages[player.guild.id] = message
        except discord.HTTPException:
            logger.exception("Failed to send now-playing message")
        await self.persist_queue(player)

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ) -> None:
        player = payload.player
        if player is not None and player.guild is not None:
            await self.persist_queue(player)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Leave when idle for ``inactive_timeout`` seconds."""
        if player.guild is None:
            return
        guild_id = player.guild.id
        channel_id = self.home_channels.get(guild_id)
        await self.clear_now_message(guild_id)
        await player.disconnect()
        await self.bot.db.clear_session(guild_id)
        self._forget_guild(guild_id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send("💤 Отключился из-за бездействия.")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # The bot itself was disconnected (kicked / moved out).
        if (
            self.bot.user is not None
            and member.id == self.bot.user.id
            and before.channel is not None
            and after.channel is None
        ):
            await self.clear_now_message(member.guild.id)
            await self.bot.db.clear_session(member.guild.id)
            self._forget_guild(member.guild.id)
            return

        # A user moved: if the bot is now alone, leave.
        if before.channel == after.channel:
            return
        player = player_of(member.guild)
        if player is None or player.channel is None:
            return
        if not any(not m.bot for m in player.channel.members):
            guild_id = member.guild.id
            await self.clear_now_message(guild_id)
            await player.disconnect()
            await self.bot.db.clear_session(guild_id)
            self._forget_guild(guild_id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self._forget_guild(guild.id)

    # ------------------------------------------------------------------ #
    #  Restart recovery
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        if self._restored:
            return
        self._restored = True
        await self._restore_sessions()

    async def _restore_sessions(self) -> None:
        try:
            sessions = await self.bot.db.load_sessions()
        except sqlite3.Error:
            logger.exception("Failed to load sessions")
            return
        for session in sessions:
            try:
                await self._restore_one(session)
            except Exception:
                logger.exception("Failed to restore guild %s", session.guild_id)

    async def _restore_one(self, session: PlayerSession) -> None:
        guild = self.bot.get_guild(session.guild_id)
        channel = guild.get_channel(session.voice_channel_id) if guild else None
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await self.bot.db.clear_session(session.guild_id)
            return
        # Only restore if real users are still listening.
        if not any(not m.bot for m in channel.members):
            await self.bot.db.clear_session(session.guild_id)
            return
        saved = await self.bot.db.load_queue(session.guild_id)
        if not saved:
            await self.bot.db.clear_session(session.guild_id)
            return

        player = await connect_and_configure(channel, self.bot)
        if session.text_channel_id:
            self.home_channels[session.guild_id] = session.text_channel_id

        for item in saved:
            try:
                found = await wavelink.Playable.search(item.uri)
            except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
                logger.warning(
                    "Skipping unresolvable track %r for guild %s",
                    item.uri,
                    session.guild_id,
                )
                continue
            if isinstance(found, wavelink.Playlist):
                found = found.tracks
            if not found:
                continue
            track = found[0]
            if item.requester:
                track.extras = {"requester": item.requester, "avatar": item.avatar}
            player.queue.put(track)

        await self.maybe_start(player)
        logger.info(
            "Restored %d tracks for guild %s", len(player.queue) + 1, session.guild_id
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Music(bot))
