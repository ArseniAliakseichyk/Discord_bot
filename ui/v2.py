"""Components V2 building blocks.

Discord's "v2" components replace the embed with a tree of layout primitives:
a :class:`discord.ui.Container` holds :class:`~discord.ui.TextDisplay` blocks,
:class:`~discord.ui.Section` rows (text plus one accessory), separators and
action rows of buttons.

Two constraints drive everything here, both enforced by discord.py itself:

* A message carrying v2 components **cannot** also carry ``content`` or
  ``embeds`` — discord.py sets the ``components_v2`` message flag
  (``discord/http.py``) and Discord rejects the combination. Text that used to
  live in ``content`` has to become a ``TextDisplay``.
* A :class:`~discord.ui.LayoutView` is capped at ``MAX_V2_COMPONENTS``
  components and ``V2_TEXT_LIMIT`` characters of display text. Long text must be
  split or truncated *before* it reaches the view, otherwise sending raises.

``PanelView`` is the base every panel inherits: it greys its components out on
timeout and reports errors instead of leaving a button silently dead.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable
from typing import Any, cast

import discord
from discord import ui

from core.constants import (
    EMBED_COLOR,
    MAX_V2_COMPONENTS,
    V2_TEXT_LIMIT,
)

logger = logging.getLogger("bot.v2")

__all__ = [
    "PanelView",
    "bullet_list",
    "clamp_text",
    "disable_all_v2",
    "embed_to_container",
    "field",
    "heading",
    "make_panel",
    "notice",
    "send_panel",
    "split_text",
]


# --------------------------------------------------------------------------- #
#  Text helpers
# --------------------------------------------------------------------------- #
def clamp_text(text: str, limit: int = V2_TEXT_LIMIT) -> str:
    """Trim ``text`` to ``limit`` characters, marking that it was cut."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def split_text(
    text: str, limit: int = V2_TEXT_LIMIT, *, total: int | None = None
) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters.

    Splits on line boundaries where possible so markdown is not cut mid-block;
    a single line longer than ``limit`` is hard-split. Never returns an empty
    chunk — a TextDisplay with empty content is rejected by Discord.

    ``total`` caps the *combined* length of the chunks. Without it, splitting a
    very long body produces many valid chunks whose sum still exceeds the view's
    4000-character budget, and the message is rejected only at send time.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if total is not None:
        text = clamp_text(text, total)
        limit = min(limit, total)
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current)
    return [c for c in chunks if c.strip()] or [text[:limit] or "—"]


def as_select(item: object) -> ui.Select[Any]:
    """Treat a ``@ui.select``-decorated attribute as the Select it is at runtime.

    The decorator's static type does not expose the instance, so mypy narrows
    the attribute to ``Never`` and rejects assignments to ``.options`` — even
    though the object really is a :class:`discord.ui.Select`. Centralised here
    so the cast is explained once rather than repeated at every call site.
    """
    return cast("ui.Select[Any]", item)


def heading(text: str, *, level: int = 2) -> str:
    """Markdown heading. Discord renders levels 1-3 only."""
    return f"{'#' * max(1, min(level, 3))} {text}"


def field(name: str, value: str, *, inline_sep: str = " ") -> str:
    """Render a label/value pair the way an embed field used to look."""
    return f"**{name}**{inline_sep}{value}"


def bullet_list(items: Iterable[str], *, bullet: str = "•") -> str:
    return "\n".join(f"{bullet} {item}" for item in items)


# --------------------------------------------------------------------------- #
#  Container construction
# --------------------------------------------------------------------------- #
def make_panel(
    *,
    title: str | None = None,
    body: str | None = None,
    accent: int | discord.Colour | None = EMBED_COLOR,
    thumbnail: str | None = None,
    extra: Iterable[ui.Item] | None = None,
) -> ui.Container:
    """Build the standard panel container used across the bot.

    ``thumbnail`` puts the image beside the title the way ``set_thumbnail`` did
    on an embed; a Section is the only v2 construct that can do that, and it
    requires an accessory, which is exactly what the thumbnail becomes.
    """
    children: list[ui.Item] = []

    if title and thumbnail:
        children.append(
            ui.Section(
                ui.TextDisplay(heading(title)),
                accessory=ui.Thumbnail(thumbnail),
            )
        )
    elif title:
        children.append(ui.TextDisplay(heading(title)))
    elif thumbnail:
        children.append(ui.MediaGallery(discord.MediaGalleryItem(thumbnail)))

    if body:
        # Reserve room for the title that was already added, and cap the total
        # so a long body cannot push the view past its 4000-character budget.
        used = sum(
            len(c.content)
            for c in children
            if isinstance(c, ui.TextDisplay)
        ) + sum(
            len(t.content)
            for c in children
            if isinstance(c, ui.Section)
            for t in c.children
            if isinstance(t, ui.TextDisplay)
        )
        budget = max(1, V2_TEXT_LIMIT - used)
        for chunk in split_text(body, budget, total=budget):
            children.append(ui.TextDisplay(chunk))

    if extra:
        children.extend(extra)

    return ui.Container(*children, accent_colour=accent)


def embed_to_container(embed: discord.Embed) -> ui.Container:
    """Render an :class:`discord.Embed` as an equivalent v2 container.

    Used to preview an embed inside a Components V2 message, which cannot carry
    a real embed. All fields collapse into a single ``TextDisplay`` on purpose:
    an embed may hold 25 of them, and one component each would blow the
    40-component budget the surrounding view has to share with its buttons.

    An embed may legally hold 6000 characters while a v2 view is capped at
    4000, so the text is spent against a shared budget and the tail is trimmed
    rather than letting Discord reject the whole message.
    """
    budget = V2_TEXT_LIMIT

    def spend(text: str) -> str:
        """Take what is left of the budget for ``text``."""
        nonlocal budget
        if budget <= 0:
            return ""
        taken = clamp_text(text, budget)
        budget -= len(taken)
        return taken

    header = ""
    if embed.author and embed.author.name:
        header += f"-# {embed.author.name}\n"
    if embed.title:
        header += f"## [{embed.title}]({embed.url})" if embed.url else f"## {embed.title}"

    header = spend(header)
    thumb = embed.thumbnail.url if embed.thumbnail else None
    container: ui.Container[Any]
    if header and thumb:
        container = ui.Container(
            ui.Section(ui.TextDisplay(header), accessory=ui.Thumbnail(thumb)),
            accent_colour=embed.colour,
        )
    else:
        container = ui.Container(accent_colour=embed.colour)
        if header:
            container.add_item(ui.TextDisplay(header))
        if thumb:
            container.add_item(ui.MediaGallery(discord.MediaGalleryItem(thumb)))

    if embed.description:
        described = spend(embed.description)
        if described:
            container.add_item(ui.TextDisplay(described))

    if embed.fields:
        blocks: list[str] = []
        for item in embed.fields:
            name = (item.name or "").strip()
            value = (item.value or "").strip()
            if not name and not value:
                blocks.append("―")  # the builder's separator field
            else:
                blocks.append(f"**{name}**\n{value}" if name else value)
        rendered = spend("\n\n".join(blocks))
        if rendered:
            container.add_item(ui.TextDisplay(rendered))

    if embed.image and embed.image.url:
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(embed.image.url)))

    if embed.footer and embed.footer.text:
        footer = spend(f"-# {embed.footer.text}")
        if footer:
            container.add_item(ui.Separator())
            container.add_item(ui.TextDisplay(footer))

    return container


def disable_all_v2(view: ui.LayoutView) -> None:
    """Grey out every interactive component anywhere in a v2 tree.

    ``walk_children`` is required here: unlike a classic ``View``, buttons live
    nested inside containers, sections and action rows rather than directly on
    the view, so iterating ``view.children`` would miss all of them.
    """
    for item in view.walk_children():
        if isinstance(item, (ui.Button, ui.Select)):
            item.disabled = True


# --------------------------------------------------------------------------- #
#  Base view
# --------------------------------------------------------------------------- #
class PanelView(ui.LayoutView):
    """LayoutView with the project's timeout and error behaviour.

    Pass ``timeout=None`` for a persistent panel; give every component an
    explicit ``custom_id`` in that case and register the view with
    ``bot.add_view`` so it survives a restart.
    """

    def __init__(self, *, timeout: float | None = 180.0) -> None:
        super().__init__(timeout=timeout)
        self._origin: discord.Interaction | None = None

    def bind(self, interaction: discord.Interaction) -> None:
        """Remember the interaction that carries this view (ephemeral panels).

        An ephemeral message exposes no ``Message`` object, so this is the only
        handle ``on_timeout`` has for greying the buttons out.
        """
        self._origin = interaction

    async def on_timeout(self) -> None:
        disable_all_v2(self)
        if self._origin is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await self._origin.edit_original_response(view=self)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: ui.Item,
    ) -> None:
        logger.error("%s failed on %r", type(self).__name__, item, exc_info=error)
        message = "⚠️ Произошла внутренняя ошибка."
        with contextlib.suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)


# --------------------------------------------------------------------------- #
#  Ready-made panels
# --------------------------------------------------------------------------- #
def notice(text: str, *, accent: int | discord.Colour | None = EMBED_COLOR) -> PanelView:
    """A whole message that is just one short line.

    Used everywhere a plain string used to be enough: a v2 message carries no
    ``content``, so even a one-line reply has to be a view.
    """
    view = PanelView(timeout=None)
    view.add_item(make_panel(body=text, accent=accent))
    return view


# --------------------------------------------------------------------------- #
#  Sending
# --------------------------------------------------------------------------- #
async def send_panel(
    interaction: discord.Interaction,
    view: ui.LayoutView,
    *,
    ephemeral: bool = True,
    bind: bool = True,
) -> None:
    """Respond to ``interaction`` with a v2 panel.

    Note there is no ``content``/``embed`` parameter by design: a v2 message
    cannot carry either. Everything visible must already be inside ``view``.
    """
    if bind and isinstance(view, PanelView):
        view.bind(interaction)
    if interaction.response.is_done():
        await interaction.followup.send(view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(view=view, ephemeral=ephemeral)


def count_components(view: ui.LayoutView) -> int:
    """Total components in the tree — compare against ``MAX_V2_COMPONENTS``."""
    return sum(1 for _ in view.walk_children())


def text_length(view: ui.LayoutView) -> int:
    """Combined TextDisplay length — compare against ``V2_TEXT_LIMIT``."""
    return view.content_length()


def fits(view: ui.LayoutView) -> bool:
    """Whether the view is within both v2 limits."""
    return count_components(view) <= MAX_V2_COMPONENTS and text_length(view) <= V2_TEXT_LIMIT
