"""Components V2 panels for the rules/verification message and for tickets.

Both panels are **persistent**: they are built with ``timeout=None``, every
component carries an explicit ``custom_id``, and ``cogs.tickets`` registers a
template instance through ``bot.add_view`` at startup. That is what lets a
button posted months ago still work after a restart.

Ticket ownership is looked up in the ``tickets`` table by channel id. The
previous implementation encoded it in the channel *topic* and parsed it back
out, which silently broke as soon as anyone edited the topic.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import discord
from discord import ui

from core.constants import V2_TEXT_LIMIT
from ui.v2 import PanelView, make_panel, split_text

logger = logging.getLogger("bot.tickets")

# --- custom_ids. Changing one orphans every panel already posted. ----------- #
CID_VERIFY = "rules:verify"
CID_OPEN_TICKET = "rules:ticket"
CID_HELP = "rules:help"
CID_CLAIM = "ticket:claim"
CID_CLOSE = "ticket:close"

PANEL_COLOR = 0xFF69B4

TICKET_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("question", "Вопрос", "❓"),
    ("role", "Проблема с ролью", "🎭"),
    ("report", "Жалоба на участника", "⚠️"),
    ("bug", "Ошибка бота или сервера", "🐛"),
    ("other", "Другое", "💬"),
)
CATEGORY_LABELS = {value: label for value, label, _ in TICKET_CATEGORIES}

#: Shown when a guild has not set its own text via ``/ticket config rules``.
#: The server's own rules from before the rewrite, word for word: the rewrite
#: had cut them down to a generic summary, losing the hierarchy section, the
#: bot-channel rule and the tone the server wrote them in. Changed: the typo
#: "аппеляцию", and the closing call to action, which moved to RULES_FOOTER
#: below a separator (the embed faked that line with underscores).
DEFAULT_RULES = """# 🦩 Welcome to Гача 🦩

> Мы здесь, чтобы получать удовольствие, играть и отдыхать.
> Мы – **взрослое** комьюнити (__18+__).

> ### ✅ Ознакомься с правилами ниже и жми **«Согласен»**, чтобы войти.
> 📨 Возникли проблемы? Жми **«Связаться с администрацией»**.

## 🏛️ Наши Три Столпа
### Это __нерушимые__ правила. Нарушение = бан.
1.  **АДЕКВАТНОСТЬ:** Мы 18+. Веди себя как взрослый. Без нытья, токсичности и \
детских истерик. (Разумеется, мы понимаем, что такое юмор. И даже черный 🥰)
2.  **УВАЖЕНИЕ:** Оскорбление семьи или переход на личности = *мгновенный бан* \
(Если ваш оппонент не против, то вперед). Политические дебаты – окей, но без грязи.
3.  **ЧЕСТНОСТЬ:** `Скама – нет.` Фишинг, вирусы, попытки кражи аккаунтов – это \
перманентный бан. Без шансов на апелляцию. Я не шучу. Реально сразу в бан 😇.

## 🗣️ Голос vs. ⌨️ Текст
* **В Голосе:** Ты *почти* свободен. Трэш-ток, шутки, «performance» – всё можно, \
пока это не нарушает Три Столпа.
* **В Тексте:** __Строгая модерация.__ Никакого спама или флуда. Все команды ботов – \
в `канале - 🎧bot`.

## 👑 Иерархия Гачи
> **Администрация** (`🤍Император🤍`, `⚔️Лорды🛡️`) – это закон. Не спорь в общем чате, \
для этого есть тикеты.
> **Продвижение:** Начинаешь как `Гражданин`. Проявляй активность, вливайся в комьюнити \
и со временем сможешь получить __кастомную роль__, а может и модерку, кто знает 🤭.

## 🎙️ Твой Сетап
* **Микрофон – обязателен.** Мы играем в команде. Никто не хочет слушать твой \
перфоратор или эхо из 2005-го.
* *Рекомендуем: `HyperX Cloud` или `SteelSeries Arctis`.*
"""

#: The call to action under the rules, above the buttons.
RULES_FOOTER = "### Жми   `✅ Согласен`   и погнали!"


def _support_role(guild: discord.Guild, support_role_id: int | None) -> discord.Role | None:
    return guild.get_role(support_role_id) if support_role_id else None


def is_support(member: discord.Member, support_role_id: int | None) -> bool:
    """Whether ``member`` may triage tickets on this guild."""
    if member.guild_permissions.manage_guild:
        return True
    role = _support_role(member.guild, support_role_id)
    return role is not None and role in member.roles


# --------------------------------------------------------------------------- #
#  Modal
# --------------------------------------------------------------------------- #
class TicketModal(ui.Modal, title="Обращение в поддержку"):
    """Ticket form.

    The category is a real select rather than free text, so tickets arrive
    pre-sorted; select-in-modal became available in discord.py 2.6.
    """

    category: ui.Label = ui.Label(
        text="Категория",
        description="К чему относится обращение",
        component=ui.Select(
            custom_id="ticket_category",
            options=[
                discord.SelectOption(label=label, value=value, emoji=emoji)
                for value, label, emoji in TICKET_CATEGORIES
            ],
        ),
    )
    subject: ui.Label = ui.Label(
        text="Тема",
        description="Коротко, 1–2 слова",
        component=ui.TextInput(
            custom_id="ticket_subject",
            placeholder="Например: не выдалась роль",
            max_length=50,
            required=True,
        ),
    )
    body: ui.Label = ui.Label(
        text="Подробное описание",
        description="Что случилось, когда, ссылки и скриншоты по возможности",
        component=ui.TextInput(
            custom_id="ticket_body",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True,
        ),
    )

    def __init__(self, cog: TicketHost) -> None:
        super().__init__()
        self.cog = cog

    @property
    def category_value(self) -> str:
        component = self.category.component
        assert isinstance(component, ui.Select)
        return component.values[0] if component.values else "other"

    @property
    def subject_value(self) -> str:
        component = self.subject.component
        assert isinstance(component, ui.TextInput)
        return component.value

    @property
    def body_value(self) -> str:
        component = self.body.component
        assert isinstance(component, ui.TextInput)
        return component.value

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(
            interaction,
            category=self.category_value,
            subject=self.subject_value,
            body=self.body_value,
        )

    # Modal.on_error takes (interaction, error); mypy resolves the signature
    # against BaseView.on_error, which also takes the failing item.
    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        logger.error("Ticket modal failed", exc_info=error)
        message = "⚠️ Не удалось создать обращение. Попробуйте позже."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


# --------------------------------------------------------------------------- #
#  Rules / verification panel
# --------------------------------------------------------------------------- #
class RulesActions(ui.ActionRow["RulesPanel"]):
    @ui.button(
        label="Согласен с правилами",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id=CID_VERIFY,
    )
    async def verify(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.cog.verify_member(interaction)

    @ui.button(
        label="Связаться с администрацией",
        style=discord.ButtonStyle.primary,
        emoji="📨",
        custom_id=CID_OPEN_TICKET,
    )
    async def open_ticket(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.cog.prompt_ticket(interaction)

    @ui.button(
        label="Команды бота",
        style=discord.ButtonStyle.secondary,
        emoji="📖",
        custom_id=CID_HELP,
    )
    async def show_help(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.cog.show_help(interaction)


def _split_heading(text: str) -> tuple[str, str]:
    """The opening of the rules (up to the first ``##`` section) and the rest."""
    lines = text.strip().splitlines()
    for index, line in enumerate(lines[1:], 1):
        if line.startswith("## "):
            return "\n".join(lines[:index]).strip(), "\n".join(lines[index:]).strip()
    return text.strip(), ""


class RulesPanel(PanelView):
    """The message new members land on: rules, verification, support, help.

    Laid out as the embed it replaced: the server icon small beside the
    welcome, the rules below it, the call to action and the buttons last.
    """

    def __init__(
        self,
        cog: TicketHost,
        *,
        rules_text: str | None = None,
        icon_url: str | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        head, rest = _split_heading(rules_text or DEFAULT_RULES)
        container: ui.Container[RulesPanel] = ui.Container(accent_colour=PANEL_COLOR)
        if icon_url:
            container.add_item(ui.Section(ui.TextDisplay(head), accessory=ui.Thumbnail(icon_url)))
        else:
            container.add_item(ui.TextDisplay(head))
        budget = max(1, V2_TEXT_LIMIT - len(head) - len(RULES_FOOTER))
        for chunk in split_text(rest, budget, total=budget) if rest else []:
            container.add_item(ui.TextDisplay(chunk))
        container.add_item(ui.Separator())
        if rules_text is None:
            # A guild's own text ends however it likes; the default ends here.
            container.add_item(ui.TextDisplay(RULES_FOOTER))
        container.add_item(RulesActions())
        self.add_item(container)


# --------------------------------------------------------------------------- #
#  In-ticket controls
# --------------------------------------------------------------------------- #
class TicketActions(ui.ActionRow["TicketControls"]):
    @ui.button(
        label="Взять в работу",
        style=discord.ButtonStyle.success,
        emoji="🙋",
        custom_id=CID_CLAIM,
    )
    async def claim(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.cog.claim_ticket(interaction)

    @ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id=CID_CLOSE,
    )
    async def close(self, interaction: discord.Interaction, _: ui.Button) -> None:
        view = self.view
        assert view is not None
        await view.cog.close_ticket(interaction)


class TicketControls(PanelView):
    """Header panel inside a ticket channel, with the triage buttons."""

    def __init__(
        self,
        cog: TicketHost,
        *,
        number: int = 0,
        owner: discord.abc.User | None = None,
        category: str | None = None,
        subject: str = "",
        body: str = "",
        claimed_by: discord.abc.User | None = None,
        closed: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog

        if closed:
            title = f"🔒 Тикет #{number:04d} — закрыт"
            accent: int = 0xED4245
        elif claimed_by is not None:
            title = f"🟢 Тикет #{number:04d} — в работе"
            accent = 0x57F287
        else:
            title = f"📨 Тикет #{number:04d} — ожидает обработки"
            accent = 0xFEE75C

        lines: list[str] = []
        if owner is not None:
            lines.append(f"**Автор:** {owner.mention} (`{owner.id}`)")
        if category:
            lines.append(f"**Категория:** {CATEGORY_LABELS.get(category, category)}")
        if subject:
            lines.append(f"**Тема:** {subject}")
        if claimed_by is not None:
            lines.append(f"**В работе у:** {claimed_by.mention}")

        container = make_panel(title=title, body="\n".join(lines), accent=accent)
        if body:
            container.add_item(ui.Separator())
            container.add_item(ui.TextDisplay(f"**Описание**\n>>> {body}"))

        actions = TicketActions()
        if claimed_by is not None or closed:
            # Already triaged: claiming again is meaningless.
            actions.remove_item(actions.claim)
        if closed:
            actions.remove_item(actions.close)
        if len(actions.children) > 0:
            container.add_item(ui.Separator())
            container.add_item(actions)

        self.add_item(container)


@runtime_checkable
class TicketHost(Protocol):
    """What the panels need from the cog that drives them.

    A Protocol rather than a base class: ``cogs.tickets.Tickets`` is already a
    ``commands.Cog``, and structural typing keeps the UI free of any import
    from the cogs package (which would be circular).
    """

    async def verify_member(self, interaction: discord.Interaction) -> None: ...
    async def prompt_ticket(self, interaction: discord.Interaction) -> None: ...
    async def show_help(self, interaction: discord.Interaction) -> None: ...
    async def claim_ticket(self, interaction: discord.Interaction) -> None: ...
    async def close_ticket(self, interaction: discord.Interaction) -> None: ...
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        *,
        category: str,
        subject: str,
        body: str,
    ) -> None: ...
