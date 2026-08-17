"""Builder state: the embed under construction and every mutation on it.

Deliberately free of any Discord UI class, so the rules that used to be spread
across modal callbacks live in one testable place. Each mutation takes the index
it acts on as an argument rather than reading a shared ``selected_field_index``
attribute — with two pickers open at once, that shared attribute made the second
one silently edit the field chosen in the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import discord

from ui.builder.colors import expand_color_tags

PublishFormat = Literal["embed", "v2"]

#: Zero-width space — an embed field needs a non-empty name/value to render.
ZERO_WIDTH_SPACE = "​"

#: Discord's per-embed limits.
MAX_FIELDS = 25
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_FOOTER = 2048
#: Combined length of title, description, fields, footer and author.
MAX_TOTAL = 6000


class BuilderError(Exception):
    """A mutation the user asked for cannot be applied; message is user-facing."""


@dataclass
class BuilderState:
    embed: discord.Embed = field(
        default_factory=lambda: discord.Embed(
            title="Заголовок", description="Текст ...", color=discord.Color.blurple()
        )
    )
    message_content: str | None = None
    publish_format: PublishFormat = "embed"

    # ------------------------------------------------------------------ #
    #  Fields
    # ------------------------------------------------------------------ #
    @property
    def field_count(self) -> int:
        return len(self.embed.fields)

    def _check_index(self, index: int) -> None:
        if not 0 <= index < self.field_count:
            raise BuilderError(
                f"❌ Поля #{index + 1} больше нет — обновите список."
            )

    def ensure_room(self) -> None:
        if self.field_count >= MAX_FIELDS:
            raise BuilderError(f"❌ Достигнут лимит в {MAX_FIELDS} полей.")

    def add_field(self, name: str, value: str, *, inline: bool) -> None:
        self.ensure_room()
        self.embed.add_field(
            name=name[:MAX_FIELD_NAME], value=value[:MAX_FIELD_VALUE], inline=inline
        )

    def set_field(self, index: int, name: str, value: str, *, inline: bool) -> None:
        self._check_index(index)
        self.embed.set_field_at(
            index,
            name=name[:MAX_FIELD_NAME],
            value=value[:MAX_FIELD_VALUE],
            inline=inline,
        )

    def remove_field(self, index: int) -> None:
        self._check_index(index)
        self.embed.remove_field(index)

    def add_separator(self) -> None:
        self.ensure_room()
        self.embed.add_field(
            name=ZERO_WIDTH_SPACE, value=ZERO_WIDTH_SPACE, inline=False
        )

    def move_field(self, source: int, before: int) -> None:
        """Move the field at ``source`` so it sits immediately before ``before``.

        The naive ``insert(before, pop(source))`` is off by one when moving a
        field forward: popping first shifts everything after it left, so the
        item lands *after* the target instead of before it.
        """
        self._check_index(source)
        self._check_index(before)
        if source == before:
            raise BuilderError("❌ Нельзя переместить поле на его же место.")
        # Embed.fields returns copies in discord.py 2.x, so rebuild explicitly
        # rather than mutating that list (which would be a no-op).
        items = [(f.name, f.value, f.inline) for f in self.embed.fields]
        moved = items.pop(source)
        items.insert(before - 1 if source < before else before, moved)
        self.embed.clear_fields()
        for name, value, inline in items:
            self.embed.add_field(name=name, value=value, inline=inline)

    def field_labels(self) -> list[str]:
        """Menu labels for the field pickers."""
        labels: list[str] = []
        for index, item in enumerate(self.embed.fields, 1):
            name = (item.name or "").strip()
            labels.append(
                f"Поле #{index}: {name[:80]}" if name.strip(ZERO_WIDTH_SPACE) else
                f"Поле #{index}: — разделитель —"
            )
        return labels

    # ------------------------------------------------------------------ #
    #  Whole-embed edits
    # ------------------------------------------------------------------ #
    def apply_main(
        self,
        *,
        title: str | None,
        url: str | None,
        description: str | None,
        color: discord.Color | None,
        clear_color: bool,
        timestamp: bool,
    ) -> None:
        """Apply the "main settings" form as one atomic change.

        The caller validates the colour first; previously the title and
        description were written before the colour was parsed, so a malformed
        colour left the embed half-updated with no preview refresh.
        """
        self.embed.title = title or None
        self.embed.url = url or None
        self.embed.description = description or None
        if clear_color:
            self.embed.colour = None
        elif color is not None:
            self.embed.colour = color
        self.embed.timestamp = discord.utils.utcnow() if timestamp else None

    def set_media(self, kind: str, url: str | None) -> None:
        if kind == "image":
            self.embed.set_image(url=url)
        else:
            self.embed.set_thumbnail(url=url)

    def media_url(self, kind: str) -> str | None:
        media = self.embed.image if kind == "image" else self.embed.thumbnail
        return media.url if media else None

    # ------------------------------------------------------------------ #
    #  Publishing
    # ------------------------------------------------------------------ #
    def total_length(self) -> int:
        """Characters Discord counts against the 6000-per-embed budget."""
        total = len(self.embed.title or "") + len(self.embed.description or "")
        for item in self.embed.fields:
            total += len(item.name or "") + len(item.value or "")
        if self.embed.footer and self.embed.footer.text:
            total += len(self.embed.footer.text)
        if self.embed.author and self.embed.author.name:
            total += len(self.embed.author.name)
        return total

    def validate(self) -> str | None:
        """Return a user-facing problem, or None when the embed can be sent.

        Without this the publish step failed with a bare HTTP 400 that told the
        user nothing about which limit they had crossed.
        """
        if self.total_length() > MAX_TOTAL:
            return (
                f"❌ Эмбед слишком длинный: {self.total_length()} символов "
                f"при лимите {MAX_TOTAL}. Сократите текст или уберите поля."
            )
        if not any(
            (
                self.embed.title,
                self.embed.description,
                self.embed.fields,
                self.embed.image,
                self.embed.author,
            )
        ):
            return "❌ Эмбед пуст — добавьте заголовок, текст или поле."
        return None

    def final_embed(self) -> discord.Embed:
        """A copy with ``{color:…}`` tags expanded, ready to publish."""
        final = self.embed.copy()
        if final.description:
            final.description = expand_color_tags(final.description)
        for index, item in enumerate(final.fields):
            final.set_field_at(
                index,
                name=item.name,
                value=expand_color_tags(item.value or ""),
                inline=item.inline,
            )
        return final
