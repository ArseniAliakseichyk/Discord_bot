"""The builder panel: live preview plus the control rows."""

from __future__ import annotations

import contextlib
import logging

import discord
from discord import ui

from core.bot import MusicBot
from core.constants import BUILDER_TIMEOUT
from ui.builder.rows import ColorRow, ContentRow, FieldRow, MediaRow, PublishRow
from ui.builder.state import BuilderState
from ui.v2 import PanelView, embed_to_container, make_panel
from utils.mentions import mentions_for_free_text, mentions_for_role

logger = logging.getLogger("bot.builder")


def publish_mentions(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role | None,
) -> discord.AllowedMentions:
    """Mentions the invoker is actually entitled to, for the published message.

    Being allowed to run /constructor must not grant the ability to ping roles
    the user could not ping themselves.
    """
    if interaction.guild is None:
        return discord.AllowedMentions.none()
    free_text = mentions_for_free_text(interaction.user, channel, interaction.guild)
    role_mentions = mentions_for_role(interaction.user, channel, role)
    if free_text.roles is True or role_mentions.roles is True:
        roles: list[discord.Role] | bool = True
    else:
        collected = list(free_text.roles) if isinstance(free_text.roles, list) else []
        if isinstance(role_mentions.roles, list):
            collected.extend(r for r in role_mentions.roles if r not in collected)
        roles = collected or False
    return discord.AllowedMentions(everyone=free_text.everyone, roles=roles, users=True)


class GigaBuilderView(PanelView):
    """Interactive announcement builder.

    The panel is rebuilt from :class:`BuilderState` on every change, so the
    preview can never drift from the data being edited.
    """

    def __init__(
        self,
        author: discord.User | discord.Member,
        target_channel: discord.TextChannel,
        role_to_mention: discord.Role | None,
        bot: MusicBot,
    ) -> None:
        super().__init__(timeout=BUILDER_TIMEOUT)
        self.author = author
        self.target_channel = target_channel
        self.role_to_mention = role_to_mention
        self.bot = bot
        self.state = BuilderState()
        self.message: discord.InteractionMessage | None = None
        self.render()

    # ------------------------------------------------------------------ #
    #  Rendering
    # ------------------------------------------------------------------ #
    def render(self) -> None:
        self.clear_items()
        state = self.state

        note = (
            "классический эмбед"
            if state.publish_format == "embed"
            else "контейнер Components V2"
        )
        overview = [f"Канал: {self.target_channel.mention} · формат: **{note}**"]
        if self.role_to_mention:
            overview.append(f"Упоминание: {self.role_to_mention.mention}")
        overview.append(
            f"-# Символов: {state.total_length()} / 6000 · полей: {state.field_count} / 25"
        )
        self.add_item(
            make_panel(title="🚀 Конструктор анонсов", body="\n".join(overview))
        )

        if state.message_content:
            self.add_item(
                ui.TextDisplay(f"**Текст над постом:**\n{state.message_content}")
            )

        self.add_item(embed_to_container(state.embed))

        for row in (
            ContentRow(),
            ColorRow(),
            MediaRow(),
            FieldRow(),
            PublishRow(state.publish_format),
        ):
            self.add_item(row)

    async def update_preview(self) -> None:
        if self.message is None:
            return
        self.render()
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            logger.warning("Builder preview message not found (deleted?)")
            self.stop()
        except discord.HTTPException:
            logger.exception("Could not refresh the builder preview")

    async def finish(self, interaction: discord.Interaction, text: str) -> None:
        """Collapse the builder into a single closing line."""
        self.clear_items()
        self.add_item(make_panel(body=text))
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(view=self)
            else:
                await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            logger.debug("Could not close the builder", exc_info=True)
        self.stop()

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Это не ваш конструктор!", ephemeral=True, delete_after=5
            )
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: ui.Item
    ) -> None:
        logger.exception("Error in GigaBuilderView", exc_info=error)
        message = "⚠️ Произошла внутренняя ошибка."
        with contextlib.suppress(discord.HTTPException, discord.InteractionResponded):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    async def on_timeout(self) -> None:
        self.clear_items()
        self.add_item(make_panel(body="⏰ Конструктор закрыт по таймауту."))
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    # ------------------------------------------------------------------ #
    #  Publishing
    # ------------------------------------------------------------------ #
    async def publish(self, interaction: discord.Interaction) -> None:
        # Check the Discord limits before spending the interaction response:
        # publishing an oversized embed used to fail with a bare HTTP 400.
        problem = self.state.validate()
        if problem is not None:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        final = self.state.final_embed()

        # Answer first — a slow send would otherwise miss the response window.
        busy = PanelView(timeout=None)
        busy.add_item(make_panel(body="📨 Публикую…"))
        await interaction.response.edit_message(view=busy)

        guild = interaction.guild
        me = guild.me if guild is not None else None
        if me is not None and not self.target_channel.permissions_for(me).send_messages:
            await self.finish(
                interaction, f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
            return

        allowed = publish_mentions(interaction, self.target_channel, self.role_to_mention)
        mention = (
            self.role_to_mention.mention
            if self.role_to_mention and (allowed.everyone or allowed.roles)
            else ""
        )
        content = f"{mention} {self.state.message_content or ''}".strip()

        try:
            if self.state.publish_format == "v2":
                post = PanelView(timeout=None)
                if content:
                    # A v2 message has no `content`; a mention only notifies
                    # when it is real text inside the message body.
                    post.add_item(ui.TextDisplay(content))
                post.add_item(embed_to_container(final))
                await self.target_channel.send(view=post, allowed_mentions=allowed)
            else:
                await self.target_channel.send(
                    content=content or None, embed=final, allowed_mentions=allowed
                )
        except discord.Forbidden:
            await self.finish(
                interaction, f"❌ У бота нет прав писать в {self.target_channel.mention}."
            )
        except discord.HTTPException:
            logger.exception("Failed to publish the announcement")
            await self.finish(interaction, "⚠️ Не удалось опубликовать анонс.")
        else:
            await self.finish(interaction, "✅ **Анонс опубликован!**")
