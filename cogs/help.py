"""Interactive /help, rendered with Components V2.

The pages are generated from the commands actually registered on ``bot.tree``,
not from a hand-written list. A hand-written list drifts: the previous version
advertised commands that did not exist and omitted ones that did.

Categories the invoker cannot use are hidden, so a regular member is not shown
a menu of moderation commands that will refuse them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from discord import app_commands, ui
from discord.ext import commands

from core.bot import MusicBot
from core.constants import EMBED_COLOR
from ui.v2 import PanelView, as_select, make_panel, send_panel
from utils.checks import guild_authorized

logger = logging.getLogger("bot.help")

HELP_TIMEOUT = 300

#: Cog class name -> (menu label, emoji, one-line summary). Order is the menu
#: order. A cog missing here simply does not get a page.
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "Music": ("Музыка", "🎶", "Воспроизведение, очередь и режимы повтора."),
    "Voice": ("Голос", "🔊", "Подключение бота к голосовым каналам."),
    "Tickets": ("Правила и тикеты", "🎫", "Верификация и обращения в поддержку."),
    "Admin": ("Объявления", "📢", "Быстрые анонсы с упоминанием ролей."),
    "Builder": ("Конструктор", "🛠️", "Визуальный сборщик постов."),
    "Moderation": ("Модерация", "🛡️", "Предупреждения, мут, кик, бан, очистка."),
    "GuildSettingsCog": ("Настройки", "⚙️", "Параметры сервера: DJ-роль, канал, громкость."),
    "Owner": ("Владелец", "👑", "Управление белым списком серверов."),
}

MAIN_PAGE = "main"


def _describe(command: app_commands.Command | app_commands.Group) -> str:
    return command.description or "—"


class HelpSelect(ui.ActionRow["HelpPanel"]):
    @ui.select(
        placeholder="Выберите раздел…",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label="Главная", value=MAIN_PAGE)],
    )
    async def choose(
        self, interaction: discord.Interaction, select: ui.Select
    ) -> None:
        view = self.view
        assert view is not None
        await view.show(interaction, select.values[0])


class HelpPanel(PanelView):
    """Category menu over the live command tree."""

    def __init__(self, cog: Help, user: discord.abc.User) -> None:
        super().__init__(timeout=HELP_TIMEOUT)
        self.cog = cog
        self.user = user
        self.pages = cog.build_pages(user)
        self._render(MAIN_PAGE)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Это меню открыл другой пользователь — вызовите `/help` сами.",
                ephemeral=True,
            )
            return False
        return True

    def _render(self, page: str) -> None:
        """Rebuild the tree for ``page``. Cheap enough to redo on every switch."""
        self.clear_items()

        if page == MAIN_PAGE or page not in self.pages:
            title = "👋 Справка по боту"
            body = (
                "Я умею проигрывать музыку с **YouTube**, **Spotify** и локальных "
                "файлов, вести тикеты и собирать посты.\n\n"
                "Выберите раздел в меню ниже.\n\n"
                + "\n".join(
                    f"{emoji} **{label}** — {summary}"
                    for label, emoji, summary in (
                        (p.label, p.emoji, p.summary) for p in self.pages.values()
                    )
                )
            )
            accent: int = EMBED_COLOR
        else:
            current = self.pages[page]
            title = f"{current.emoji} {current.label}"
            body = current.body
            accent = current.accent

        container = make_panel(title=title, body=body, accent=accent)

        if self.pages:
            row = HelpSelect()
            as_select(row.choose).options = [
                discord.SelectOption(
                    label="Главная", value=MAIN_PAGE, emoji="👋", default=page == MAIN_PAGE
                ),
                *(
                    discord.SelectOption(
                        label=p.label,
                        value=key,
                        emoji=p.emoji,
                        description=p.summary[:100],
                        default=page == key,
                    )
                    for key, p in self.pages.items()
                ),
            ]
            container.add_item(ui.Separator())
            container.add_item(row)

        self.add_item(container)

    async def show(self, interaction: discord.Interaction, page: str) -> None:
        self._render(page)
        await interaction.response.edit_message(view=self)


@dataclass(slots=True)
class HelpPage:
    label: str
    emoji: str
    summary: str
    body: str
    accent: int = EMBED_COLOR


class Help(commands.Cog):
    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Page construction
    # ------------------------------------------------------------------ #
    @staticmethod
    def _required_permissions(
        command: app_commands.Command | app_commands.Group,
    ) -> discord.Permissions | None:
        """Everything Discord requires for ``command``, parents included.

        ``default_permissions`` may sit on any node of the tree, and Discord
        applies the whole chain. ``/ticket config category`` carries none itself
        and hangs off a ``ticket`` group that carries none either - the
        Manage Server requirement lives on the ``config`` group in the middle,
        so checking only the command and its root missed it.
        """
        required = discord.Permissions.none()
        node: app_commands.Command | app_commands.Group | None = command
        while node is not None:
            if node.default_permissions is not None:
                required |= node.default_permissions
            node = node.parent
        return required if required.value else None

    @classmethod
    def _allowed(
        cls, command: app_commands.Command | app_commands.Group, user: discord.abc.User
    ) -> bool:
        """Whether ``user`` could plausibly run ``command``.

        Mirrors what Discord shows in the command picker, so the help page and
        the picker cannot disagree.
        """
        required = cls._required_permissions(command)
        if required is None:
            return True
        if not isinstance(user, discord.Member):
            return False
        return user.guild_permissions.is_superset(required)

    def _lines_for(
        self, cog: commands.Cog, user: discord.abc.User
    ) -> list[str]:
        """Render every command belonging to ``cog`` that ``user`` may use."""
        lines: list[str] = []
        for command in sorted(
            self.bot.tree.walk_commands(), key=lambda c: c.qualified_name
        ):
            if getattr(command, "binding", None) is not cog:
                continue
            if isinstance(command, app_commands.Group):
                continue  # the group itself carries no usage, its children do
            if not self._allowed(command, user):
                continue
            lines.append(f"**/{command.qualified_name}** — {_describe(command)}")
        return lines

    def build_pages(self, user: discord.abc.User) -> dict[str, HelpPage]:
        pages: dict[str, HelpPage] = {}
        for cog_name, (label, emoji, summary) in CATEGORIES.items():
            cog = self.bot.get_cog(cog_name)
            if cog is None:
                continue  # extension not loaded — do not advertise it
            lines = self._lines_for(cog, user)
            if not lines:
                continue
            pages[cog_name] = HelpPage(
                label=label,
                emoji=emoji,
                summary=summary,
                body="\n".join(lines),
                accent=EMBED_COLOR,
            )
        return pages

    # ------------------------------------------------------------------ #
    #  Entry points
    # ------------------------------------------------------------------ #
    async def send_help_panel(self, interaction: discord.Interaction) -> None:
        """Also used by the "Команды бота" button on the rules panel."""
        await send_panel(interaction, HelpPanel(self, interaction.user), ephemeral=True)

    @app_commands.command(name="help", description="Показать интерактивный список команд")
    @guild_authorized()
    async def help_command(self, interaction: discord.Interaction) -> None:
        await self.send_help_panel(interaction)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Help(bot))
