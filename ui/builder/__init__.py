"""Announcement builder (the ``/constructor`` command).

Split by responsibility so each piece can be read and tested on its own:

``state``    the embed under construction and every mutation on it — no UI
``colors``   colour presets, ``{color:…}`` markup, hex parsing
``modals``   the input forms
``fields``   pickers for editing, deleting and reordering fields
``images``   picking an image by upload or by URL
``rows``     the panel's button rows
``panel``    the panel itself, assembling the preview and the rows
"""

from __future__ import annotations

from ui.builder.colors import PRESET_COLORS, expand_color_tags, parse_hex_color
from ui.builder.panel import GigaBuilderView, publish_mentions
from ui.builder.state import BuilderError, BuilderState

__all__ = [
    "PRESET_COLORS",
    "BuilderError",
    "BuilderState",
    "GigaBuilderView",
    "expand_color_tags",
    "parse_hex_color",
    "publish_mentions",
]
