# AstraBot - Discord Bot

## Структура
```
bot.py              # Точка входа, события, логирование
config/settings.py  # Конфигурация из .env
core/
  state.py          # Глобальное состояние (queue, current, looping)
  player.py         # Воспроизведение FFmpeg
  queue_manager.py  # Обработка очереди треков
  voice.py          # Подключение к VC
commands/
  music/            # /play, /queue, /shuffle, /clear
  utility/          # /help, /join, /leave, /announce, /constructor, /jointo
cogs/ticket_system/ # Тикеты и верификация
ui/controls.py      # Кнопки управления плеером
utils/yt_utils.py   # yt-dlp обертка с кэшем
```

## Технологии
- Python 3.12, discord.py 2.3+
- yt-dlp + FFmpeg для аудио
- cachetools (TTL 2ч), tenacity (retry)

## Ключевые паттерны
- **Состояние**: модуль `core/state.py` - глобальные переменные + asyncio.Lock
- **Очередь**: `state.queue[]` + `state.pending_queue[]`
- **Плейбэк**: `play_next()` - рекурсивный вызов после завершения трека
- **Тикеты**: persistent views, счетчик в `ticket_counter.txt`

## Оптимизации (audio_manager.py)
- **Prefetch**: URL следующего трека загружается заранее
- **Двойной кэш**: метаданные (24ч) + URL (5ч)
- **FFmpeg**: быстрый старт (-analyzeduration 0 -probesize 32768)
- **User-Agent**: обход блокировок YouTube

## Источники музыки
- YouTube: прямой URL или поиск
- Spotify: парсинг title → поиск на YT
- Локальные: папка `./music/`

## Конфигурация (.env)
```
DISCORD_TOKEN, LOG_CHANNEL_ID, ALLOWED_ROLES
VERIFY_ROLE_ID, TICKET_CATEGORY_ID, SUPPORT_ROLE_ID
GUILD_ID, CREATOR_ID, ADMIN_ROLE_ID, MODERATOR_ROLE_ID
EXCLUDED_USER_IDS, DEFAULT_CHANNEL
```

## Команды
| Музыка | Утилиты |
|--------|---------|
| /play, /queue, /shuffle, /clear | /help, /join, /leave |
| Кнопки: ⏸️▶️⏭️⏹️🔁 | /announce, /constructor, /jointo |

## Особенности
- AFK таймаут: 10 минут
- Cooldown /play: 5 сек
- Плейлисты заблокированы
- Логи: Discord канал + bot.log
