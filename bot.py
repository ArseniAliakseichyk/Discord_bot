"""Discord Music Bot entry point."""

from __future__ import annotations

import discord
from pydantic import ValidationError

from config import get_settings
from core.bot import MusicBot
from utils.logging import setup_logging


def main() -> None:
    setup_logging()

    try:
        settings = get_settings()
    except ValidationError as exc:
        raise SystemExit(f"❌ Ошибка конфигурации (.env): {exc}") from exc

    bot = MusicBot(settings)
    try:
        bot.run(settings.discord_token.get_secret_value(), log_handler=None)
    except discord.LoginFailure as exc:
        raise SystemExit(f"❌ Не удалось войти: проверьте DISCORD_TOKEN. {exc}") from exc
    except discord.PrivilegedIntentsRequired as exc:
        raise SystemExit(
            "❌ В Developer Portal не включены привилегированные intents "
            f"(Message Content и Server Members). {exc}"
        ) from exc


if __name__ == "__main__":
    main()
