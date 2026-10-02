"""A stand-in for Discord's interaction machinery.

Every "this interaction failed" and every hung button comes from the same
place: a callback that returned without acknowledging the interaction, or one
that acknowledged it twice. Discord gives a callback three seconds to call
exactly one of ``send_message``, ``edit_message``, ``defer`` or ``send_modal``;
anything else is a visible bug.

``drive`` reproduces :meth:`discord.ui.View._scheduled_task` exactly - the same
order of ``_run_checks``, ``interaction_check``, callback and ``on_error`` - so
a test exercises the real dispatch path rather than calling the callback
directly and missing the guards around it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
from discord import ui


class DoubleResponse(RuntimeError):
    """Raised when a callback acknowledges the same interaction twice."""


@dataclass
class Record:
    """What a callback did with its interaction."""

    acks: list[str] = field(default_factory=list)
    #: send_message calls, i.e. direct replies.
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: edit_message calls, i.e. the pressed message redrawn.
    redraws: list[dict[str, Any]] = field(default_factory=list)
    followups: list[dict[str, Any]] = field(default_factory=list)
    edits: list[dict[str, Any]] = field(default_factory=list)
    modals: list[ui.Modal] = field(default_factory=list)

    @property
    def acknowledged(self) -> bool:
        return bool(self.acks)

    @property
    def told_user(self) -> bool:
        """Whether the presser was given any words, however delivered."""
        return bool(self.messages or self.followups)


class FakeResponse:
    def __init__(self, record: Record, message: Any = None) -> None:
        self._record = record
        # edit_message changes the message the component is on, as in Discord.
        self._message = message

    def is_done(self) -> bool:
        return self._record.acknowledged

    def _ack(self, kind: str) -> None:
        if self._record.acknowledged:
            # discord.py raises InteractionResponded here; a callback that hits
            # this in production shows the user an error instead of the result.
            raise DoubleResponse(f"interaction acknowledged twice: {self._record.acks} then {kind}")
        self._record.acks.append(kind)

    async def send_message(self, content: str | None = None, **kwargs: Any) -> None:
        self._ack("send_message")
        self._record.messages.append({"content": content, **kwargs})

    async def edit_message(self, **kwargs: Any) -> None:
        self._ack("edit_message")
        self._record.redraws.append(kwargs)
        if self._message is not None and "view" in kwargs and hasattr(self._message, "view"):
            self._message.view = kwargs["view"]

    async def defer(self, **kwargs: Any) -> None:
        self._ack("defer")

    async def send_modal(self, modal: ui.Modal) -> None:
        self._ack("send_modal")
        self._record.modals.append(modal)


class FakeFollowup:
    def __init__(self, record: Record) -> None:
        self._record = record

    async def send(self, content: str | None = None, **kwargs: Any) -> Any:
        if not self._record.acknowledged:
            # Discord rejects a followup before the interaction is acknowledged.
            raise RuntimeError("followup.send() before the interaction was acknowledged")
        message = MagicMock(spec=discord.WebhookMessage)
        self._record.followups.append({"content": content, "message": message, **kwargs})
        return message


class FakeInteraction:
    """Enough of :class:`discord.Interaction` for a view callback to run."""

    def __init__(
        self,
        *,
        user: Any,
        guild: Any = None,
        channel: Any = None,
        message: Any = None,
        values: list[str] | None = None,
    ) -> None:
        self.record = Record()
        self.response = FakeResponse(self.record, message)
        self.followup = FakeFollowup(self.record)
        self.user = user
        self.guild = guild
        self.guild_id = getattr(guild, "id", None)
        self.channel = channel
        self.channel_id = getattr(channel, "id", None)
        self.message = message
        # Select values must travel in `data`: Select._refresh_state reads them
        # from there and overwrites anything set on the component directly.
        self.data: dict[str, Any] = {"values": list(values or [])}
        self.client = MagicMock()
        self.type = discord.InteractionType.component
        self.extras: dict[str, Any] = {}
        self.command = None

    async def edit_original_response(self, **kwargs: Any) -> Any:
        if not self.record.acknowledged:
            raise RuntimeError("edit_original_response() before acknowledging")
        self.record.edits.append(kwargs)
        return MagicMock(spec=discord.InteractionMessage)

    async def delete_original_response(self) -> None:
        if not self.record.acknowledged:
            raise RuntimeError("delete_original_response() before acknowledging")

    async def original_response(self) -> Any:
        return MagicMock(spec=discord.InteractionMessage)


async def drive(
    view: ui.LayoutView | ui.View, item: ui.Item, interaction: FakeInteraction
) -> Record:
    """Dispatch ``item`` the way discord.py's own scheduler does."""
    try:
        item._refresh_state(interaction, interaction.data)  # type: ignore[arg-type]
        allowed = await item._run_checks(interaction) and await view.interaction_check(  # type: ignore[arg-type]
            interaction  # type: ignore[arg-type]
        )
        if not allowed:
            return interaction.record
        await item.callback(interaction)  # type: ignore[arg-type]
    except Exception as error:  # mirrors _scheduled_task's catch-all
        if isinstance(error, DoubleResponse):
            raise
        await view.on_error(interaction, error, item)  # type: ignore[arg-type]
    return interaction.record


def find_item(view: ui.LayoutView | ui.View, key: str) -> ui.Item:
    """A button or select by custom_id, label, or placeholder text."""
    for item in interactive_items(view):
        if (
            getattr(item, "custom_id", None) == key
            or getattr(item, "label", None) == key
            or key in (getattr(item, "placeholder", "") or "")
        ):
            return item
    raise LookupError(f"no component {key!r} in {type(view).__name__}")


def interactive_items(view: ui.LayoutView | ui.View) -> list[ui.Item]:
    """Every button and select in the tree, however deeply nested."""
    return [
        item
        for item in view.walk_children()
        if isinstance(item, (ui.Button, ui.Select)) and item.is_dispatchable()
    ]


# --------------------------------------------------------------------------- #
#  Discord object doubles
# --------------------------------------------------------------------------- #
def make_role(role_id: int = 100, *, position: int = 1, name: str = "role") -> Any:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.name = name
    role.position = position
    role.mention = f"<@&{role_id}>"
    role.__ge__ = lambda self, other: position >= getattr(other, "position", 0)
    role.__le__ = lambda self, other: position <= getattr(other, "position", 0)
    role.__lt__ = lambda self, other: position < getattr(other, "position", 0)
    role.__gt__ = lambda self, other: position > getattr(other, "position", 0)
    return role


def make_member(
    member_id: int = 1,
    *,
    guild: Any = None,
    roles: list[Any] | None = None,
    top_role_position: int = 1,
    permissions: discord.Permissions | None = None,
    bot: bool = False,
) -> Any:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.bot = bot
    member.display_name = f"user{member_id}"
    member.name = f"user{member_id}"
    member.mention = f"<@{member_id}>"
    member.roles = roles if roles is not None else []
    member.top_role = make_role(900 + member_id, position=top_role_position)
    member.guild = guild
    member.guild_permissions = discord.Permissions.all() if permissions is None else permissions
    member.display_avatar = MagicMock(url="https://cdn.example/a.png")
    member.voice = None
    member.timed_out_until = None
    member.add_roles = AsyncMock()
    member.send = AsyncMock()
    member.timeout = AsyncMock()
    member.kick = AsyncMock()
    return member


def make_channel(channel_id: int = 10, *, guild: Any = None, can_send: bool = True) -> Any:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = "channel"
    channel.mention = f"<#{channel_id}>"
    channel.guild = guild
    channel.topic = None
    channel.send = AsyncMock(return_value=MagicMock(spec=discord.Message))
    channel.edit = AsyncMock()
    channel.set_permissions = AsyncMock()
    channel.purge = AsyncMock(return_value=[])
    channel.permissions_for = MagicMock(
        return_value=discord.Permissions.all() if can_send else discord.Permissions.none()
    )
    return channel


def make_guild(guild_id: int = 411981432768954369, *, bot_top_position: int = 50) -> Any:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "guild"
    guild.owner_id = 999
    guild.icon = None
    guild.me = make_member(2, guild=None, top_role_position=bot_top_position, bot=True)
    guild.me.guild = guild
    guild.roles = []
    guild.get_role = MagicMock(return_value=None)
    guild.get_channel = MagicMock(return_value=None)
    guild.get_member = MagicMock(return_value=None)
    guild.create_text_channel = AsyncMock()
    guild.ban = AsyncMock()
    guild.unban = AsyncMock()
    return guild


def make_player(guild: Any, *, playing: bool = True, paused: bool = False) -> Any:
    """A wavelink player double wired into ``guild.voice_client``.

    ``player_of`` reads ``guild.voice_client``, so attaching it here is what
    makes the playback buttons take their real code path instead of the
    "not connected" branch.
    """
    import wavelink

    player = MagicMock(spec=wavelink.Player)
    player.guild = guild
    player.playing = playing
    player.paused = paused
    player.position = 1000
    player.volume = 100
    player.current = MagicMock(spec=wavelink.Playable)
    player.current.title = "track"
    player.current.length = 10_000
    player.current.is_stream = False
    player.current.is_seekable = True
    player.current.uri = "https://example/track"
    player.current.author = "artist"
    player.current.artwork = None
    player.current.source = "youtube"
    player.current.extras = None
    player.queue = wavelink.Queue()
    player.auto_queue = wavelink.Queue()
    player.autoplay = wavelink.AutoPlayMode.partial
    player.channel = make_channel(77, guild=guild)

    player.pause = AsyncMock()
    player.skip = AsyncMock()
    player.seek = AsyncMock()
    player.set_volume = AsyncMock()
    player.disconnect = AsyncMock()
    guild.voice_client = player
    return player


def make_track(title: str = "track") -> Any:
    """A real Playable, so wavelink Queue type checks accept it."""
    import wavelink

    return wavelink.Playable(
        {
            "encoded": f"enc-{title}",
            "info": {
                "identifier": title,
                "isSeekable": True,
                "author": "artist",
                "length": 10_000,
                "isStream": False,
                "position": 0,
                "title": title,
                "uri": f"https://example/{title}",
                "sourceName": "youtube",
                "artworkUrl": None,
                "isrc": None,
            },
            "pluginInfo": {},
            "userData": {},
        }
    )


# --------------------------------------------------------------------------- #
#  A text channel that records what was posted, and how it changed
# --------------------------------------------------------------------------- #
class SentMessage:
    """A now-playing message that records whether it was edited or deleted."""

    _counter = 0

    def __init__(self, channel=None) -> None:
        SentMessage._counter += 1
        self.id = SentMessage._counter
        self.channel = channel
        self.deleted = False
        self.edits = 0
        #: The view after the latest edit; None until the message is edited.
        self.view = None
        self.flags = discord.MessageFlags()

    async def edit(self, **kwargs):
        await asyncio.sleep(0)
        self.edits += 1
        if "view" in kwargs:
            self.view = kwargs["view"]
        return self

    async def delete(self) -> None:
        await asyncio.sleep(0)
        if self.deleted:
            raise discord.NotFound(MagicMock(status=404), "already deleted")
        self.deleted = True


def make_home_channel(channel_id: int = 55):
    """The text channel the bot posts now-playing panels into.

    Built on a TextChannel spec so it satisfies the
    ``isinstance(channel, discord.abc.Messageable)`` guard in the listeners;
    a plain object makes them return early and the test proves nothing.
    """
    channel = make_channel(channel_id)
    channel.sent = []
    channel.texts = []

    async def send(content: str | None = None, **kwargs):
        # A real send is an HTTP request and always yields to the loop; one
        # that does not hides every race around posting a panel.
        await asyncio.sleep(0)
        if content is not None:
            channel.texts.append(content)
        message = SentMessage(channel)
        channel.sent.append(message)
        return message

    channel.send = AsyncMock(side_effect=send)
    return channel


def idle_text(message) -> str | None:
    """The text of a retired panel, or None if it still has controls.

    A panel is retired by editing it into a view with no buttons; deleting it
    and posting a separate notice left two messages for one event.
    """
    from discord import ui

    view = getattr(message, "view", None)
    if view is None:
        return None
    if any(isinstance(i, (ui.Button, ui.Select)) for i in view.walk_children()):
        return None
    return "\n".join(i.content for i in view.walk_children() if isinstance(i, ui.TextDisplay))
