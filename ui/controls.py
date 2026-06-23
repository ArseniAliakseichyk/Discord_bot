"""Now-playing embed and playback control buttons (wavelink-based)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import wavelink

from utils.checks import user_is_dj
from utils.formatting import format_duration

if TYPE_CHECKING:
    from cogs.music import Music

_SOURCE_NAMES = {
    "youtube": "YouTube",
    "youtubemusic": "YouTube Music",
    "soundcloud": "SoundCloud",
    "local": "Локальный файл",
    "http": "Прямая ссылка",
}


def _requester(track: wavelink.Playable) -> tuple[str | None, str | None]:
    extras = getattr(track, "extras", None)
    if extras is None:
        return None, None
    return getattr(extras, "requester", None), getattr(extras, "avatar", None)


def now_playing_embed(track: wavelink.Playable, player: wavelink.Player) -> discord.Embed:
    """Build the "Now playing" embed for a track on a player."""
    source = (track.source or "").lower()
    is_local = source == "local"
    embed = discord.Embed(
        title="🎵 Сейчас играет",
        description=f"[{track.title}]({track.uri or 'https://youtube.com'})",
        color=discord.Color.green() if is_local else discord.Color.gold(),
    )
    if track.artwork:
        embed.set_thumbnail(url=track.artwork)

    if player.paused:
        status = "⏸️ На паузе"
    elif player.autoplay == wavelink.AutoPlayMode.enabled:
        status = "📻 Автоплей"
    else:
        status = "▶️ Воспроизведение"

    duration = "🔴 LIVE" if track.is_stream else format_duration(track.length / 1000)
    embed.add_field(name="Длительность", value=duration, inline=True)
    embed.add_field(
        name="Источник",
        value=_SOURCE_NAMES.get(source, source.title() or "YouTube"),
        inline=True,
    )
    embed.add_field(name="Статус", value=status, inline=True)

    if not track.is_stream and track.length:
        embed.add_field(
            name="Прогресс",
            value=f"{format_duration(player.position / 1000)} / "
            f"{format_duration(track.length / 1000)}",
            inline=False,
        )

    name, avatar = _requester(track)
    if name:
        embed.set_footer(text=f"Добавлено: {name}", icon_url=avatar)
    return embed


class NowPlayingControls(discord.ui.View):
    """Pause / resume / skip / stop buttons under the now-playing message."""

    def __init__(self, cog: "Music") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _player(self, interaction: discord.Interaction) -> wavelink.Player | None:
        if interaction.guild is None:
            return None
        return interaction.guild.voice_client  # type: ignore[return-value]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return False
        if await user_is_dj(self.cog.bot, interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Нужна DJ-роль для управления воспроизведением.", ephemeral=True
        )
        return False

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary)
    async def pause(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        player = self._player(interaction)
        if player and player.playing and not player.paused:
            await player.pause(True)
            await self.cog.refresh_now_message(player)

    @discord.ui.button(label="▶️ Продолжить", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        player = self._player(interaction)
        if player and player.paused:
            await player.pause(False)
            await self.cog.refresh_now_message(player)

    @discord.ui.button(label="⏭️ Скип", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        player = self._player(interaction)
        if player and (player.playing or player.current):
            await player.skip(force=True)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        player = self._player(interaction)
        if player:
            await self.cog.stop_player(player)
