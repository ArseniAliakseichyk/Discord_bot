"""Discord Music Bot entry point."""

from __future__ import annotations

from config import get_settings
from core.bot import MusicBot
from utils.logging import setup_logging


def main() -> None:
    setup_logging()

    try:
        settings = get_settings()
    except Exception as exc:  # ValidationError etc. — fail clearly
        raise SystemExit(f"❌ Ошибка конфигурации (.env): {exc}") from exc

    bot = MusicBot(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
