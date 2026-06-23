"""Music commands backed by Lavalink via wavelink.

Per-guild state lives on the wavelink ``Player`` (one per guild) and its
``player.queue`` — there is no global state.
"""

from __future__ import annotations

import logging
import os

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from core.bot import MusicBot
from core.db import SavedTrack
from ui.controls import NowPlayingControls, now_playing_embed
from ui.search import SearchView
from utils.checks import guild_authorized, has_dj, in_command_channel
from utils.formatting import format_duration

logger = logging.getLogger("bot.music")

SEARCH_RESULTS = 5
QUEUE_PAGE = 20


class Music(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        # Per-guild now-playing message and the channel where commands were used.
        self.now_messages: dict[int, discord.Message] = {}
        self.home_channels: dict[int, int] = {}
        self._restored = False

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def player_of(guild: discord.Guild | None) -> wavelink.Player | None:
        if guild is None:
            return None
        return guild.voice_client  # type: ignore[return-value]

    async def ensure_player(
        self, interaction: discord.Interaction
    ) -> wavelink.Player | None:
        """Return the guild player, connecting to the user's channel if needed."""
        player = self.player_of(interaction.guild)
        if player is not None:
            return player
        user = interaction.user
        if (
            not isinstance(user, discord.Member)
            or user.voice is None
            or user.voice.channel is None
        ):
            return None
        player = await user.voice.channel.connect(cls=wavelink.Player)
        player.autoplay = wavelink.AutoPlayMode.partial
        player.inactive_timeout = self.bot.settings.inactive_timeout
        settings = await self.bot.db.get_settings(interaction.guild.id)
        volume = (
            settings.default_volume
            if settings.default_volume is not None
            else self.bot.settings.default_volume
        )
        try:
            await player.set_volume(volume)
        except Exception:
            logger.exception("Failed to set initial volume")
        return player

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

    async def _resolve(self, query: str) -> wavelink.Search:
        local_path = os.path.join(self.bot.settings.music_folder, query)
        if os.path.isfile(local_path):
            container_path = f"{self.bot.settings.lavalink_local_dir.rstrip('/')}/{query}"
            return await wavelink.Playable.search(container_path)
        return await wavelink.Playable.search(
            query, source=wavelink.TrackSource.YouTube
        )

    async def maybe_start(self, player: wavelink.Player) -> None:
        if not player.playing and not player.queue.is_empty():
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
        tracks: list[SavedTrack] = []
        if player.current is not None and player.current.uri:
            tracks.append(self._to_saved(player.current))
        tracks.extend(self._to_saved(t) for t in player.queue if t.uri)
        text_channel_id = self.home_channels.get(player.guild.id)
        try:
            await self.bot.db.save_session(
                player.guild.id, player.channel.id, text_channel_id, tracks
            )
        except Exception:
            logger.exception("Failed to persist session")

    async def refresh_now_message(self, player: wavelink.Player) -> None:
        message = self.now_messages.get(player.guild.id)
        if message is not None and player.current is not None:
            try:
                await message.edit(
                    embed=now_playing_embed(player.current, player),
                    view=NowPlayingControls(self),
                )
            except discord.HTTPException:
                pass

    async def clear_now_message(self, guild_id: int) -> None:
        message = self.now_messages.pop(guild_id, None)
        if message is not None:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    async def stop_player(self, player: wavelink.Player) -> None:
        guild_id = player.guild.id
        player.autoplay = wavelink.AutoPlayMode.partial
        player.queue.clear()
        try:
            player.auto_queue.clear()
        except Exception:
            pass
        if player.playing or player.current is not None:
            await player.skip(force=True)
        await self.clear_now_message(guild_id)
        await self.bot.db.clear_session(guild_id)

    async def add_and_play(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
        member: discord.Member,
    ) -> None:
        """Used by the search menu: enqueue a chosen track and start if idle."""
        player = await self.ensure_player(interaction)
        if player is None or interaction.guild is None:
            return
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]
        self._set_requester(track, member)
        player.queue.put(track)
        await self.maybe_start(player)
        await self.persist_queue(player)

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="play", description="Воспроизвести трек/плейлист с YouTube или локальный файл"
    )
    @app_commands.describe(query="Ссылка, поисковый запрос или имя локального файла")
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        if player is None:
            await interaction.followup.send("❌ Сначала зайдите в голосовой канал.")
            return
        self.home_channels[interaction.guild.id] = interaction.channel_id  # type: ignore[assignment]

        try:
            result = await self._resolve(query.strip())
        except Exception:
            logger.exception("Search failed for %r", query)
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
    @app_commands.checks.cooldown(1, 5.0)
    @guild_authorized()
    @in_command_channel()
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if (
            not isinstance(interaction.user, discord.Member)
            or interaction.user.voice is None
        ):
            await interaction.followup.send("❌ Сначала зайдите в голосовой канал.")
            return
        try:
            result = await wavelink.Playable.search(
                query, source=wavelink.TrackSource.YouTube
            )
        except Exception:
            logger.exception("Search failed for %r", query)
            await interaction.followup.send("⚠️ Ошибка поиска.")
            return
        if isinstance(result, wavelink.Playlist):
            result = result.tracks
        if not result:
            await interaction.followup.send("⚠️ Ничего не найдено.")
            return
        tracks = list(result)[:SEARCH_RESULTS]
        view = SearchView(self, tracks, interaction.user)
        await interaction.followup.send(
            "🔎 Результаты поиска — выберите трек:", view=view
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="now", description="Показать текущий трек")
    @guild_authorized()
    async def now(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
        if player is None or player.current is None:
            await interaction.response.send_message(
                "❌ Сейчас ничего не играет.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=now_playing_embed(player.current, player), ephemeral=True
        )

    @app_commands.command(name="queue", description="Показать очередь")
    @guild_authorized()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
        if player is None or (player.queue.is_empty() and player.current is None):
            await interaction.response.send_message("🚫 Очередь пуста.", ephemeral=True)
            return
        lines: list[str] = []
        if player.current is not None:
            lines.append(f"▶️ **{player.current.title}**")
        for i, track in enumerate(player.queue, 1):
            if i > QUEUE_PAGE:
                lines.append(f"… и ещё {len(player.queue) - QUEUE_PAGE}")
                break
            lines.append(f"`{i}.` {track.title}")
        embed = discord.Embed(
            title="📜 Очередь", description="\n".join(lines)[:4000], color=0x2B2D31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="shuffle", description="Перемешать очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
        if player is not None and not player.queue.is_empty():
            player.queue.shuffle()
            await self.persist_queue(player)
            await interaction.response.send_message("🔀 Очередь перемешана.")
        else:
            await interaction.response.send_message("🚫 Очередь пуста.", ephemeral=True)

    @app_commands.command(name="clear", description="Очистить очередь")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def clear(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
        if player is not None and not player.queue.is_empty():
            player.queue.clear()
            await self.persist_queue(player)
            await interaction.response.send_message("🧹 Очередь очищена.")
        else:
            await interaction.response.send_message("🚫 Очередь пуста.", ephemeral=True)

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
        if player is not None and (player.playing or player.current is not None):
            await player.skip(force=True)
            await interaction.response.send_message("⏭️ Пропущено.")
        else:
            await interaction.response.send_message(
                "❌ Сейчас ничего не играет.", ephemeral=True
            )

    @app_commands.command(name="pause", description="Пауза")
    @guild_authorized()
    @has_dj()
    @in_command_channel()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self.player_of(interaction.guild)
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
        player = self.player_of(interaction.guild)
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
        player = self.player_of(interaction.guild)
        if player is not None:
            await self.stop_player(player)
            await interaction.response.send_message(
                "⏹️ Воспроизведение остановлено, очередь очищена."
            )
        else:
            await interaction.response.send_message(
                "❌ Бот не в голосовом канале.", ephemeral=True
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
        player = self.player_of(interaction.guild)
        if player is None:
            await interaction.response.send_message(
                "❌ Бот не в голосовом канале.", ephemeral=True
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
                embed=now_playing_embed(payload.track, player),
                view=NowPlayingControls(self),
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
            return

        # A user moved: if the bot is now alone, leave.
        if before.channel == after.channel:
            return
        player = self.player_of(member.guild)
        if player is None or player.channel is None:
            return
        if not any(not m.bot for m in player.channel.members):
            guild_id = member.guild.id
            await self.clear_now_message(guild_id)
            await player.disconnect()
            await self.bot.db.clear_session(guild_id)

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
        except Exception:
            logger.exception("Failed to load sessions")
            return
        for session in sessions:
            try:
                await self._restore_one(session)
            except Exception:
                logger.exception("Failed to restore guild %s", session.guild_id)

    async def _restore_one(self, session) -> None:
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

        player: wavelink.Player = await channel.connect(cls=wavelink.Player)
        player.autoplay = wavelink.AutoPlayMode.partial
        player.inactive_timeout = self.bot.settings.inactive_timeout
        settings = await self.bot.db.get_settings(session.guild_id)
        volume = (
            settings.default_volume
            if settings.default_volume is not None
            else self.bot.settings.default_volume
        )
        try:
            await player.set_volume(volume)
        except Exception:
            logger.exception("Failed to set volume on restore")
        if session.text_channel_id:
            self.home_channels[session.guild_id] = session.text_channel_id

        for item in saved:
            try:
                found = await wavelink.Playable.search(item.uri)
            except Exception:
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
