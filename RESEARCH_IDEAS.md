# Исследование: Идеи для расширения AstraBot

> Дата исследования: 29.01.2026
> Цель: Анализ возможностей расширения функционала Discord бота

---

## Содержание

1. [Игры и развлечения](#1-игры-и-развлечения)
2. [Админ-функции и модерация](#2-админ-функции-и-модерация)
3. [Другие полезные функции](#3-другие-полезные-функции)
4. [Текущее состояние бота](#4-текущее-состояние-бота)
5. [Приоритеты реализации](#5-приоритеты-реализации)
6. [Технические рекомендации](#6-технические-рекомендации)
7. [Источники](#7-источники)

---

## 1. Игры и развлечения

### 1.1 Казино и азартные игры

#### Популярные боты-примеры:
- **UnbelievaBoat** — блэкджек, рулетка, слоты, гонки животных
- **The Casino** — блэкджек, рулетка, слоты, market crash
- **Rocket Gambling Bot (RGB)** — интерактивные игры через реакции
- **Dank Memer** — 8.6M+ серверов, gambling + RPG + leaderboards

#### Блэкджек

**Механика:**
- Классические правила (цель: 21 очко)
- Кнопки: Hit (ещё карта), Stand (хватит), Double (удвоить)
- Визуализация карт через emoji или ASCII-арт в embed
- Автоматический расчёт выигрыша

**Пример embed:**
```
🃏 БЛЭКДЖЕК
━━━━━━━━━━━━━━━━━━
Дилер: 🂡 🂠 (?)
Ты:    🂮 🂻 (19)
━━━━━━━━━━━━━━━━━━
Ставка: 100 монет

[Hit] [Stand] [Double]
```

**Технические детали:**
- Колода: 52 карты, перемешивается каждую игру
- Хранение состояния игры в памяти (dict по user_id)
- Timeout: 60 секунд на ход

#### Слоты

**Механика:**
- 3x3 или 5x3 сетка символов
- Символы: 🍒 🍋 🍊 🍇 💎 7️⃣
- Линии выплат: горизонтальные, диагональные
- Джекпот за три 7️⃣

**Множители выплат:**
| Комбинация | Множитель |
|------------|-----------|
| 🍒🍒🍒 | x2 |
| 🍋🍋🍋 | x3 |
| 🍊🍊🍊 | x5 |
| 🍇🍇🍇 | x10 |
| 💎💎💎 | x25 |
| 7️⃣7️⃣7️⃣ | x100 (Jackpot) |

**Анимация:**
```python
# Эффект вращения через редактирование сообщения
for _ in range(3):
    await message.edit(embed=spinning_embed)
    await asyncio.sleep(0.5)
await message.edit(embed=result_embed)
```

#### Рулетка

**Типы ставок:**
- Цвет: красное/чёрное (x2)
- Чёт/нечёт (x2)
- Конкретное число (x36)
- Диапазон 1-18/19-36 (x2)
- Дюжины 1-12/13-24/25-36 (x3)

#### Dice (кости)

**Варианты:**
- Простой бросок 1-6
- Ставка на сумму двух костей
- Ставка выше/ниже 7
- PvP режим (кто больше выбросит)

#### Coin Flip

**Механика:**
- 50/50 шанс
- Ставка удваивается при выигрыше
- Анимация подбрасывания монеты
- Можно вызвать другого игрока

---

### 1.2 Экономическая система

#### Архитектура базы данных

**Таблица users:**
```sql
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    balance INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    daily_streak INTEGER DEFAULT 0,
    last_daily TEXT,
    total_earned INTEGER DEFAULT 0,
    total_spent INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**Таблица transactions:**
```sql
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    type TEXT, -- 'daily', 'game_win', 'game_loss', 'transfer', 'purchase'
    description TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**Таблица shop:**
```sql
CREATE TABLE shop (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    name TEXT,
    description TEXT,
    price INTEGER,
    type TEXT, -- 'role', 'item', 'boost'
    role_id INTEGER,
    stock INTEGER DEFAULT -1, -- -1 = unlimited
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### Способы заработка

| Способ | Награда | Кулдаун |
|--------|---------|---------|
| `/daily` | 100-500 монет | 24 часа |
| `/weekly` | 1000-2000 монет | 7 дней |
| Голосовой чат | 1 монета/минута | - |
| Сообщения | 1-5 монет | 1 минута |
| Победа в играх | Зависит от ставки | - |
| Daily streak (7 дней) | x2 бонус | - |

#### Команды экономики

```
/balance [@user]        — Показать баланс
/daily                  — Ежедневная награда
/pay @user <amount>     — Перевести монеты
/top [page]             — Таблица лидеров
/deposit <amount>       — Положить в банк
/withdraw <amount>      — Снять из банка
/shop                   — Открыть магазин
/buy <item>             — Купить предмет
/inventory              — Инвентарь
```

#### Магазин

**Типы товаров:**
- Временные роли (VIP на 30 дней)
- Постоянные роли
- Кастомные цвета ников
- Бусты для игр (x2 выигрыш на час)
- Косметика профиля

---

### 1.3 Мини-игры

#### Trivia (Викторина)

**Источники вопросов:**
- Open Trivia Database API (бесплатно, 4000+ вопросов)
- Собственная база вопросов
- Категории: общие знания, музыка, фильмы, игры, наука

**Механика:**
- 10-20 вопросов за раунд
- 15-30 секунд на ответ
- Множественный выбор (A/B/C/D) через кнопки
- Очки за скорость ответа
- Мультиплеер с таблицей результатов

**Пример:**
```
❓ ВИКТОРИНА — Вопрос 5/10
━━━━━━━━━━━━━━━━━━━━━━━━
Категория: 🎬 Фильмы

Кто режиссёр фильма "Начало" (2010)?

[A] Стивен Спилберг
[B] Кристофер Нолан  ✅
[C] Джеймс Кэмерон
[D] Мартин Скорсезе

⏱️ Осталось: 15 сек
```

#### 8ball (Магический шар)

**Ответы (21 классический):**
```python
ANSWERS = [
    # Положительные (10)
    "Бесспорно", "Предрешено", "Никаких сомнений",
    "Определённо да", "Можешь быть уверен в этом",
    "Мне кажется — да", "Вероятнее всего", "Хорошие перспективы",
    "Знаки говорят — да", "Да",
    # Нейтральные (5)
    "Пока не ясно, попробуй снова", "Спроси позже",
    "Лучше не рассказывать", "Сейчас нельзя предсказать",
    "Сконцентрируйся и спроси опять",
    # Отрицательные (6)
    "Даже не думай", "Мой ответ — нет", "По моим данным — нет",
    "Перспективы не очень", "Весьма сомнительно", "Нет"
]
```

#### Rock-Paper-Scissors (Камень-ножницы-бумага)

**Режимы:**
- vs Bot (мгновенный результат)
- vs Player (вызов через @mention)
- Турнир (bracket система)

**Реализация:**
```python
@ui.button(label="🪨", style=discord.ButtonStyle.secondary)
async def rock(self, interaction, button):
    await self.play(interaction, "rock")

@ui.button(label="📄", style=discord.ButtonStyle.secondary)
async def paper(self, interaction, button):
    await self.play(interaction, "paper")

@ui.button(label="✂️", style=discord.ButtonStyle.secondary)
async def scissors(self, interaction, button):
    await self.play(interaction, "scissors")
```

---

### 1.4 Социальные игры

#### Truth or Dare (Правда или Действие)

**База вопросов:**
- 500+ вопросов "Правда"
- 500+ заданий "Действие"
- Категории: PG (для всех), 18+ (опционально)
- Рандомный выбор с исключением повторов

**Команды:**
```
/truth              — Случайный вопрос "Правда"
/dare               — Случайное задание
/tod                — Выбор через кнопки
/tod @user          — Игра с конкретным человеком
```

#### Would You Rather (Что бы ты выбрал)

**Механика:**
- Два варианта выбора
- Голосование через реакции/кнопки
- Показ статистики после голосования
- API: truthy.dev (500,000+ вопросов)

**Пример:**
```
🤔 ЧТО БЫ ТЫ ВЫБРАЛ?
━━━━━━━━━━━━━━━━━━━━
🅰️ Уметь летать

           или

🅱️ Быть невидимым
━━━━━━━━━━━━━━━━━━━━
Голосов: 0 | ⏱️ 30 сек
```

#### Never Have I Ever (Я никогда не...)

**Механика:**
- Случайное утверждение
- Игроки отвечают 👍 (делал) или 👎 (не делал)
- Подсчёт "грехов" для каждого игрока
- Таблица результатов в конце

---

### 1.5 Организация игр на сервере

#### Вариант 1: Отдельный канал #casino

**Преимущества:**
- Все игры в одном месте
- Закреплённый leaderboard
- Не мешает другим каналам
- Легко модерировать

**Настройка:**
- Slowmode 5-10 секунд
- Только команды игр разрешены
- Автоудаление не-игровых сообщений

#### Вариант 2: Треды

**Преимущества:**
- Каждая сессия изолирована
- Автоархивация через 24ч
- Параллельные игры возможны
- Чистый основной канал

**Реализация:**
```python
thread = await channel.create_thread(
    name=f"🎰 Блэкджек — {user.name}",
    auto_archive_duration=1440,  # 24 часа
    type=discord.ChannelType.public_thread
)
```

#### Вариант 3: Ephemeral сообщения (Рекомендуется для казино)

**Преимущества:**
- Приватность (только игрок видит)
- Нет спама в канале
- Быстрее работает
- Идеально для одиночных игр

**Использование:**
```python
await interaction.response.send_message(
    embed=game_embed,
    view=game_view,
    ephemeral=True
)
```

---

## 2. Админ-функции и модерация

### 2.1 Панель управления

#### Концепция админ-панели

Одна команда `/admin` открывает интерактивную панель:

```
┌──────────────────────────────────────────────┐
│  🛡️ ПАНЕЛЬ АДМИНИСТРАТОРА                   │
│  Сервер: My Discord Server                   │
├──────────────────────────────────────────────┤
│                                              │
│  [👥 Участники]     [📊 Статистика]          │
│  [🔒 Модерация]     [⚙️ Настройки]           │
│  [📋 Логи]          [💾 Бэкапы]              │
│  [🎁 Giveaway]      [🎭 Роли]                │
│                                              │
├──────────────────────────────────────────────┤
│  📈 Онлайн: 89/1234 | 💬 Сегодня: 2,456 msg  │
└──────────────────────────────────────────────┘
```

#### Секция "Участники"

- Список последних вступивших
- Поиск по нику/ID
- Быстрые действия: kick, ban, mute, warn
- История модерации пользователя

#### Секция "Статистика"

- Активность по дням (график)
- Топ активных каналов
- Рост/отток участников
- Пик онлайна

#### Секция "Настройки"

- Включение/выключение модулей
- Настройка автомодерации
- Каналы для логов
- Роли модераторов

---

### 2.2 Авто-модерация

#### Антиспам

**Параметры детекции:**
```python
SPAM_CONFIG = {
    "message_limit": 5,      # сообщений
    "time_window": 10,       # секунд
    "duplicate_limit": 3,    # одинаковых сообщений
    "emoji_limit": 10,       # эмодзи в сообщении
    "mention_limit": 5,      # упоминаний
    "caps_threshold": 0.7,   # 70% заглавных букв
}
```

**Действия при нарушении:**
1. Первое: Предупреждение (ephemeral)
2. Второе: Удаление + публичное предупреждение
3. Третье: Мут на 10 минут
4. Четвёртое: Мут на 1 час

#### Фильтр слов

**Структура:**
```python
WORD_FILTER = {
    "blacklist": ["слово1", "слово2"],
    "whitelist_channels": [123456789],  # каналы-исключения
    "whitelist_roles": [987654321],     # роли-исключения
    "action": "delete",  # delete, warn, mute
    "log": True
}
```

**Обход защиты:**
- Нормализация текста (убрать спецсимволы)
- Замена похожих символов (a→а, e→е, o→о)
- Проверка без пробелов

#### Антирейд

**Детекция:**
```python
RAID_CONFIG = {
    "join_threshold": 10,     # пользователей
    "join_window": 60,        # секунд
    "new_account_days": 7,    # аккаунт моложе X дней
    "action": "lockdown"      # lockdown, kick_new, alert
}
```

**Режим Lockdown:**
- Приостановка всех инвайтов
- Требование верификации для новых
- Уведомление админов
- Автоотключение через 10 минут

#### Фильтр ссылок

**Типы:**
- Discord инвайты (discord.gg/*)
- Известные фишинг-домены
- Сокращатели ссылок (bit.ly, t.co)

**Whitelist:**
```python
ALLOWED_DOMAINS = [
    "youtube.com", "youtu.be",
    "spotify.com", "open.spotify.com",
    "twitch.tv", "twitter.com",
    "github.com", "imgur.com"
]
```

---

### 2.3 Система предупреждений

#### База данных

```sql
CREATE TABLE warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    guild_id INTEGER,
    moderator_id INTEGER,
    reason TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,  -- NULL = permanent
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE mod_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    moderator_id INTEGER,
    action TEXT,  -- warn, mute, kick, ban, unban, unmute
    reason TEXT,
    duration INTEGER,  -- секунды, NULL для permanent
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### Команды модерации

```
/warn @user <reason>
  → Выдаёт предупреждение
  → Логирует в #mod-logs
  → DM пользователю (опционально)
  → Проверяет авто-наказания

/warnings @user
  → Показывает все активные предупреждения
  → История с датами и модераторами

/clearwarnings @user [warn_id]
  → Убирает все или конкретное предупреждение
  → Требует причину

/mute @user <duration> [reason]
  → Выдаёт timeout
  → Форматы: 1h, 30m, 1d, 1w
  → Максимум: 28 дней (лимит Discord)

/unmute @user
  → Снимает timeout
  → Логирует действие

/kick @user [reason]
  → Кикает с сервера
  → DM с причиной перед киком
  → Логирует

/ban @user [duration] [reason]
  → Банит пользователя
  → duration: permanent или 1d, 7d, 30d
  → delete_messages: 0, 1h, 24h, 7d

/unban <user_id>
  → Разбанивает
  → Можно по ID если нет на сервере

/modlog [@user]
  → История действий модерации
  → Фильтр по пользователю
  → Пагинация
```

#### Авто-наказания

```python
AUTO_PUNISHMENTS = {
    3: {"action": "mute", "duration": 3600},      # 3 варна = мут 1 час
    5: {"action": "mute", "duration": 86400},     # 5 варнов = мут 24 часа
    7: {"action": "ban", "duration": None}        # 7 варнов = перманент бан
}
```

#### Истечение варнов

```python
# Варны старше 30 дней автоматически деактивируются
async def cleanup_old_warnings():
    await db.execute("""
        UPDATE warnings
        SET active = FALSE
        WHERE timestamp < datetime('now', '-30 days')
        AND active = TRUE
    """)
```

---

### 2.4 Расширенное логирование

#### Канал #mod-logs

**События для логирования:**

| Событие | Информация |
|---------|------------|
| Сообщение удалено | Автор, канал, содержимое, время |
| Сообщение изменено | До/после, автор, канал |
| Участник вступил | Ник, ID, дата создания аккаунта |
| Участник вышел | Ник, роли, время на сервере |
| Роль выдана/снята | Кто, кому, какая роль |
| Канал создан/удалён | Название, категория, кто создал |
| Голосовой канал | Вход/выход/переход |
| Бан/кик/мут | Модератор, причина, длительность |

#### Формат логов

```
📝 СООБЩЕНИЕ УДАЛЕНО
━━━━━━━━━━━━━━━━━━━━━━━━
👤 Автор: User#1234 (ID: 123456789)
📍 Канал: #general
💬 Содержимое:
"Текст удалённого сообщения здесь"
📎 Вложения: image.png
🕐 Время: 29.01.2026 15:30:45
━━━━━━━━━━━━━━━━━━━━━━━━
```

```
🚪 УЧАСТНИК ВЫШЕЛ
━━━━━━━━━━━━━━━━━━━━━━━━
👤 Пользователь: User#1234
🆔 ID: 123456789
📅 На сервере: 45 дней
🎭 Роли: Member, VIP, Music Lover
🕐 Время: 29.01.2026 15:30:45
━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Реализация

```python
class ModLogger:
    def __init__(self, bot, log_channel_id):
        self.bot = bot
        self.log_channel_id = log_channel_id

    async def log(self, embed: discord.Embed):
        channel = self.bot.get_channel(self.log_channel_id)
        if channel:
            await channel.send(embed=embed)

    async def on_message_delete(self, message):
        if message.author.bot:
            return

        embed = discord.Embed(
            title="📝 Сообщение удалено",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Автор", value=f"{message.author} ({message.author.id})")
        embed.add_field(name="Канал", value=message.channel.mention)
        embed.add_field(name="Содержимое", value=message.content[:1024] or "Пусто", inline=False)

        await self.log(embed)
```

---

### 2.5 Система бэкапов

#### Что сохраняется

| Компонент | Детали |
|-----------|--------|
| Роли | Названия, цвета, права, позиции |
| Каналы | Структура, категории, права, описания |
| Настройки | Верификация, AFK, системные каналы |
| Эмодзи | Все кастомные эмодзи |
| Баны | Список забаненных с причинами |
| Настройки бота | Конфигурация модулей |

#### Структура бэкапа (JSON)

```json
{
    "version": "1.0",
    "created_at": "2026-01-29T15:30:00Z",
    "guild": {
        "name": "My Server",
        "icon_url": "...",
        "verification_level": 2,
        "default_notifications": "mentions"
    },
    "roles": [
        {
            "id": 123456789,
            "name": "Admin",
            "color": "#FF0000",
            "permissions": 8,
            "position": 10,
            "hoist": true,
            "mentionable": false
        }
    ],
    "categories": [
        {
            "id": 111111111,
            "name": "Text Channels",
            "position": 0,
            "permissions": [...]
        }
    ],
    "channels": [
        {
            "id": 222222222,
            "name": "general",
            "type": "text",
            "category_id": 111111111,
            "topic": "General chat",
            "slowmode": 0,
            "nsfw": false,
            "permissions": [...]
        }
    ],
    "emojis": [
        {
            "id": 333333333,
            "name": "custom_emoji",
            "url": "..."
        }
    ],
    "bans": [
        {
            "user_id": 444444444,
            "reason": "Spam"
        }
    ]
}
```

#### Команды

```
/backup create [name]
  → Создаёт бэкап сервера
  → Сохраняет в data/backups/
  → Возвращает ID бэкапа

/backup list
  → Показывает все бэкапы
  → Дата, размер, ID

/backup info <id>
  → Детали конкретного бэкапа
  → Что включено

/backup restore <id> [--roles] [--channels] [--emojis]
  → Восстанавливает из бэкапа
  → Опциональные флаги для частичного восстановления
  → Подтверждение перед выполнением

/backup delete <id>
  → Удаляет бэкап
```

---

### 2.6 Reaction Roles (Роли по реакциям)

#### Типы

| Тип | Описание |
|-----|----------|
| **Normal** | Клик добавляет, повторный убирает |
| **Give only** | Только добавление, нельзя убрать |
| **Take only** | Только снятие роли |
| **Unique** | Одна роль из группы (цвет профиля) |
| **Temporary** | Роль на время (24ч, 7д) |
| **Verified** | Требует другую роль |

#### Конструктор

```
/reactionrole create
  → Открывает интерактивный конструктор

Шаг 1: Выбор сообщения
  [Новое сообщение] [Существующее по ID]

Шаг 2: Добавление ролей
  Эмодзи: 🔴
  Роль: @Red Color
  Тип: Normal
  [Добавить ещё] [Готово]

Шаг 3: Настройки
  [x] Unique mode (только одна роль)
  [ ] DM уведомление
  [ ] Логировать

Шаг 4: Публикация
  Канал: #roles
  [Опубликовать]
```

#### Хранение

```sql
CREATE TABLE reaction_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER,
    emoji TEXT,  -- Unicode или custom emoji ID
    role_id INTEGER,
    type TEXT DEFAULT 'normal',
    group_name TEXT,  -- для unique mode
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

### 2.7 Giveaway система

#### Создание

```
/giveaway create
  → Модальное окно:
    - Приз (текст)
    - Длительность (1h, 1d, 7d)
    - Количество победителей (1-10)
    - Канал
    - Требования (роль, опционально)
```

#### Embed гивэвея

```
🎉 GIVEAWAY 🎉
━━━━━━━━━━━━━━━━━━━━━━━━
🎁 Приз: VIP роль на месяц

⏰ Заканчивается: через 23ч 45м
👥 Участников: 156
🏆 Победителей: 3
📋 Требования: роль @Member
━━━━━━━━━━━━━━━━━━━━━━━━
Нажми 🎉 чтобы участвовать!

Создал: @Admin
```

#### Команды управления

```
/giveaway list
  → Все активные гивы

/giveaway end <id>
  → Досрочно завершить

/giveaway reroll <id>
  → Перевыбрать победителя

/giveaway cancel <id>
  → Отменить без победителя
```

#### Выбор победителя

```python
async def pick_winners(message_id, count):
    message = await channel.fetch_message(message_id)
    reaction = discord.utils.get(message.reactions, emoji="🎉")

    users = [user async for user in reaction.users() if not user.bot]

    # Проверка требований
    eligible = []
    for user in users:
        member = guild.get_member(user.id)
        if required_role in member.roles:
            eligible.append(user)

    winners = random.sample(eligible, min(count, len(eligible)))
    return winners
```

---

### 2.8 Welcome система

#### Настройка

```
/welcome setup
  → Интерактивная настройка:
    - Канал для приветствий
    - Канал для прощаний
    - Текст сообщения (с переменными)
    - Embed или обычный текст
    - Автороль для новичков
    - DM новичкам (да/нет)
```

#### Переменные

| Переменная | Значение |
|------------|----------|
| `{user}` | @упоминание |
| `{user.name}` | Имя пользователя |
| `{user.id}` | ID пользователя |
| `{server}` | Название сервера |
| `{membercount}` | Количество участников |
| `{user.created}` | Дата создания аккаунта |

#### Пример embed

```
👋 Добро пожаловать, {user}!
━━━━━━━━━━━━━━━━━━━━━━━━
Ты {membercount}-й участник {server}!

📜 Прочитай правила в #rules
💬 Общайся в #general
🎵 Слушай музыку в #music

Аккаунт создан: {user.created}
━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 3. Другие полезные функции

### 3.1 Статистика сервера

#### Команда /stats server

```
📊 СТАТИСТИКА СЕРВЕРА
━━━━━━━━━━━━━━━━━━━━━━━━
👥 Участников
   Всего: 1,234
   Людей: 1,200
   Ботов: 34
   Онлайн: 89

📈 Активность (сегодня)
   Сообщений: 2,456
   Голосовых минут: 1,230
   Новых участников: +12
   Ушло: -3

🎵 Музыка
   Треков прослушано: 156
   Общее время: 8ч 45м

📅 За неделю
   Рост: +45 участников
   Пик онлайна: 156 (Сб, 20:00)
━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Команда /stats user

```
👤 СТАТИСТИКА: User#1234
━━━━━━━━━━━━━━━━━━━━━━━━
📅 На сервере: 156 дней
💬 Сообщений: 12,456
🎤 В голосовых: 234ч

📊 За месяц
   Сообщений: 1,234
   Активных дней: 28/30
   Любимый канал: #general

🏆 Достижения
   🥇 Топ-10 по сообщениям
   🎵 Меломан (100+ треков)
   📅 Ветеран (6+ месяцев)
━━━━━━━━━━━━━━━━━━━━━━━━
```

### 3.2 Уровни и XP

#### Система прогрессии

**Формула XP для уровня:**
```python
def xp_for_level(level):
    return 5 * (level ** 2) + 50 * level + 100

# Level 1: 155 XP
# Level 5: 475 XP
# Level 10: 1100 XP
# Level 20: 3100 XP
# Level 50: 15100 XP
```

**Заработок XP:**
- Сообщение: 15-25 XP (раз в минуту)
- Голосовой: 5 XP/минута
- Бонус за стрик: +10% за каждый день

#### Награды за уровни

```python
LEVEL_REWARDS = {
    5: {"role": "Активный"},
    10: {"role": "Постоянный", "channel": "vip-chat"},
    20: {"role": "Ветеран", "custom_color": True},
    30: {"role": "Легенда", "custom_emoji": True},
    50: {"role": "Элита", "special_perks": True}
}
```

#### Команды

```
/rank [@user]
  → Текущий уровень и прогресс
  → Карточка с аватаром и XP баром

/leaderboard [page]
  → Топ по уровням
  → Пагинация

/rewards
  → Список наград за уровни
```

### 3.3 Утилиты

#### Информационные команды

```
/ping
  → Задержка бота (WebSocket + API)

/serverinfo
  → Полная информация о сервере
  → Владелец, дата создания, буст уровень
  → Количество каналов, ролей, эмодзи

/userinfo @user
  → Информация о пользователе
  → Аватар, дата регистрации, роли
  → Статус, активность

/avatar @user
  → Аватар в полном размере
  → Кнопки: PNG, JPG, WebP, GIF

/roleinfo @role
  → Информация о роли
  → Цвет, права, участники

/channelinfo #channel
  → Информация о канале
  → Топик, slowmode, права
```

#### Опросы

```
/poll "Вопрос?" "Вариант 1" "Вариант 2" [duration]
  → Создаёт опрос с реакциями
  → До 10 вариантов
  → Таймер (опционально)
  → Результаты в конце

/quickpoll "Вопрос?"
  → Быстрый опрос да/нет
  → Реакции ✅ ❌
```

#### Напоминания

```
/remind <time> <text>
  → Напоминание через DM
  → Форматы: 1h, 30m, 2d, 1w
  → Список напоминаний: /reminders

/remind list
  → Все активные напоминания

/remind cancel <id>
  → Отменить напоминание
```

---

## 4. Текущее состояние бота

### 4.1 Что уже реализовано

#### Музыкальная система ✅
- `/play` — YouTube, Spotify (через поиск), локальные файлы
- `/now` — Текущий трек с прогресс-баром
- `/queue` — Очередь воспроизведения
- `/shuffle` — Перемешать очередь
- `/clear` — Очистить очередь
- `/join`, `/leave` — Подключение к каналам
- Интерактивные кнопки управления
- Prefetch следующего трека
- Кэширование URL (5ч) и метаданных (24ч)

#### Тикет-система ✅
- Модальное окно для создания тикета
- Автоматическое создание приватного канала
- Кнопки "Взять в работу" и "Закрыть"
- Нумерация тикетов
- Persistent views (переживает рестарт)

#### Верификация ✅
- Кнопка "Согласен с правилами"
- Автоматическая выдача роли

#### Конструктор объявлений ✅
- Визуальный билдер embed
- Поля, изображения, автор, футер
- Шаблоны (сохранение/загрузка)
- Планирование публикации
- Создание тредов
- Конструктор кнопок

#### Логирование ✅
- Файловый лог (bot.log)
- Discord канал для логов
- События: сообщения, входы/выходы, ошибки

### 4.2 Что отсутствует

#### Критически важное
- [ ] Управление очередью (`/remove`, `/move`)
- [ ] Громкость (`/volume`)
- [ ] Перемотка (`/seek`)
- [ ] Режимы повтора (`/loop off|one|all`)

#### Модерация
- [ ] `/warn`, `/mute`, `/kick`, `/ban`
- [ ] Авто-модерация (спам, слова, ссылки)
- [ ] Система предупреждений
- [ ] Расширенные логи

#### Развлечения
- [ ] Игры (казино, викторины)
- [ ] Экономика (валюта, магазин)
- [ ] Социальные игры

#### Утилиты
- [ ] `/ping`, `/serverinfo`, `/userinfo`
- [ ] Опросы
- [ ] Напоминания
- [ ] Welcome система

#### Данные
- [ ] SQLite база данных
- [ ] Статистика пользователей
- [ ] Уровни и XP

---

## 5. Приоритеты реализации

### Фаза 1: Быстрые победы (1-2 дня)

**Утилиты:**
- `/ping` — задержка бота
- `/serverinfo` — информация о сервере
- `/userinfo @user` — информация о пользователе
- `/avatar @user` — аватар пользователя

**Простые игры:**
- `/coinflip` — подбрасывание монетки
- `/dice [sides]` — бросок кубика
- `/8ball <question>` — магический шар
- `/rps` — камень-ножницы-бумага

**Музыка:**
- `/volume <1-100>` — громкость

### Фаза 2: Экономика и казино (3-5 дней)

**База данных:**
- SQLite для балансов и транзакций
- Миграция ticket_counter.txt

**Экономика:**
- `/daily` — ежедневная награда
- `/balance` — баланс
- `/pay @user <amount>` — перевод
- `/top` — таблица лидеров

**Казино:**
- `/blackjack <bet>` — блэкджек
- `/slots <bet>` — слоты
- `/coinflip <bet>` — ставка на монетку

### Фаза 3: Модерация (3-5 дней)

**Команды:**
- `/warn @user <reason>` — предупреждение
- `/warnings @user` — список предупреждений
- `/mute @user <duration> [reason]` — мут
- `/kick @user [reason]` — кик
- `/ban @user [reason]` — бан
- `/purge <count>` — удаление сообщений
- `/slowmode #channel <seconds>` — медленный режим

**Логирование:**
- Расширенный #mod-logs
- Детальные логи действий

### Фаза 4: Расширенные функции (5-7 дней)

**Авто-модерация:**
- Антиспам
- Фильтр слов
- Антирейд

**Серверные функции:**
- Welcome система
- Reaction roles
- Giveaway система

**Статистика:**
- `/stats server` — статистика сервера
- `/stats user` — статистика пользователя
- Уровни и XP (опционально)

---

## 6. Технические рекомендации

### 6.1 Структура папок

```
commands/
├── music/          # ✅ Есть
├── utility/        # ✅ Есть
├── games/          # 🆕 Казино, развлечения
│   ├── __init__.py
│   ├── blackjack.py
│   ├── slots.py
│   ├── coinflip.py
│   ├── dice.py
│   ├── eightball.py
│   └── rps.py
├── economy/        # 🆕 Валюта, магазин
│   ├── __init__.py
│   ├── balance.py
│   ├── daily.py
│   ├── pay.py
│   ├── top.py
│   └── shop.py
├── moderation/     # 🆕 Модерация
│   ├── __init__.py
│   ├── warn.py
│   ├── mute.py
│   ├── kick.py
│   ├── ban.py
│   ├── purge.py
│   └── slowmode.py
├── admin/          # 🆕 Админ-панель
│   ├── __init__.py
│   ├── panel.py
│   ├── settings.py
│   ├── backup.py
│   └── automod.py
└── info/           # 🆕 Информация
    ├── __init__.py
    ├── ping.py
    ├── serverinfo.py
    ├── userinfo.py
    └── avatar.py

data/
├── templates/      # ✅ Есть
├── backups/        # 🆕 Бэкапы сервера
├── astrabot.db     # 🆕 SQLite база
└── config.json     # 🆕 Настройки бота

cogs/
├── ticket_system/  # ✅ Есть
├── economy/        # 🆕 Экономика cog
├── leveling/       # 🆕 Уровни cog
└── automod/        # 🆕 Авто-модерация cog
```

### 6.2 База данных SQLite

```python
# config/database.py
import sqlite3
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "astrabot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            -- Экономика
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                guild_id INTEGER,
                balance INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0,
                daily_streak INTEGER DEFAULT 0,
                last_daily TEXT,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, guild_id)
            );

            -- Транзакции
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guild_id INTEGER,
                amount INTEGER,
                type TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Предупреждения
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guild_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            );

            -- Настройки сервера
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel INTEGER,
                log_channel INTEGER,
                mute_role INTEGER,
                automod_enabled BOOLEAN DEFAULT FALSE,
                settings_json TEXT DEFAULT '{}'
            );

            -- Reaction roles
            CREATE TABLE IF NOT EXISTS reaction_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                message_id INTEGER,
                emoji TEXT,
                role_id INTEGER,
                type TEXT DEFAULT 'normal'
            );
        """)
        await db.commit()
```

### 6.3 Пример игры (Блэкджек)

```python
# commands/games/blackjack.py
import discord
from discord import app_commands, ui
import random

CARDS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
SUITS = ['♠️', '♥️', '♦️', '♣️']

class BlackjackGame:
    def __init__(self, user_id: int, bet: int):
        self.user_id = user_id
        self.bet = bet
        self.deck = [(card, suit) for card in CARDS for suit in SUITS]
        random.shuffle(self.deck)
        self.player_hand = []
        self.dealer_hand = []
        self.game_over = False

    def deal_initial(self):
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def card_value(self, card):
        if card[0] in ['J', 'Q', 'K']:
            return 10
        elif card[0] == 'A':
            return 11
        return int(card[0])

    def hand_value(self, hand):
        value = sum(self.card_value(c) for c in hand)
        aces = sum(1 for c in hand if c[0] == 'A')
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def format_hand(self, hand, hide_second=False):
        if hide_second:
            return f"{hand[0][0]}{hand[0][1]} 🂠"
        return " ".join(f"{c[0]}{c[1]}" for c in hand)

class BlackjackView(ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game

    @ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: ui.Button):
        self.game.player_hand.append(self.game.deck.pop())

        if self.game.hand_value(self.game.player_hand) > 21:
            self.game.game_over = True
            await self.end_game(interaction, "bust")
        else:
            await self.update_game(interaction)

    @ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: ui.Button):
        # Дилер берёт карты до 17
        while self.game.hand_value(self.game.dealer_hand) < 17:
            self.game.dealer_hand.append(self.game.deck.pop())

        self.game.game_over = True
        await self.end_game(interaction, self.determine_winner())

    @ui.button(label="Double", style=discord.ButtonStyle.success, emoji="💰")
    async def double(self, interaction: discord.Interaction, button: ui.Button):
        self.game.bet *= 2
        self.game.player_hand.append(self.game.deck.pop())

        if self.game.hand_value(self.game.player_hand) > 21:
            self.game.game_over = True
            await self.end_game(interaction, "bust")
        else:
            # Автоматически stand после double
            while self.game.hand_value(self.game.dealer_hand) < 17:
                self.game.dealer_hand.append(self.game.deck.pop())
            self.game.game_over = True
            await self.end_game(interaction, self.determine_winner())

@app_commands.command(name="blackjack", description="Играть в блэкджек")
async def blackjack(interaction: discord.Interaction, bet: int):
    # Проверка баланса и создание игры
    game = BlackjackGame(interaction.user.id, bet)
    game.deal_initial()

    view = BlackjackView(game)
    embed = create_game_embed(game)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
```

---

## 7. Источники

### Казино и азартные игры
- [Best Discord Gambling Bots](https://99bitcoins.com/best-bitcoin-casino/discord-gambling-bots/)
- [UnbelievaBoat](https://unbelievaboat.com/)
- [The Casino Bot](https://discord.bots.gg/bots/585235000459264005)
- [GitHub - Casino-Bot](https://github.com/keonnk/Casino-Bot)

### Экономика
- [MEE6 Economy](https://wiki.mee6.xyz/en/plugins/economy)
- [Dank Memer](https://dankmemer.lol/)
- [Tatsu Economy](https://tatsu.gg/economy)
- [Discord Virtual Currency Guide](https://www.discordstatistics.com/blog/using-virtual-currency-and-games-with-discord-bots)

### Мини-игры и викторины
- [TriviaBot](https://lakeys.net/triviabot/)
- [Open Trivia Database](https://opentdb.com/)
- [Discord Trivia Library](https://github.com/Elitezen/discord-trivia)

### RPG и уровни
- [RPGBot](https://top.gg/bot/305177429612298242)
- [Discord Leveling System](https://github.com/Defxult/discordLevelingSystem)
- [Tatsu Leveling](https://tatsu.gg/leveling)

### Социальные игры
- [Would You Bot](https://wouldyoubot.gg/)
- [Truth or Dare Bot](https://truthordarebot.xyz/)

### Модерация
- [MEE6 Moderator](https://wiki.mee6.xyz/plugins/moderator)
- [Carl-bot](https://carl.gg/)
- [Dyno Bot](https://dyno.gg/)
- [Discord Auto-Moderation](https://discord.com/safety/auto-moderation-in-discord)

### Бэкапы
- [Xenon Bot](https://xenon.bot/)
- [VaultCord](https://vaultcord.com/)
- [RestoreCord](https://restorecord.com/)

### Giveaway
- [GiveawayBot](https://giveawaybot.party/)

### Статистика
- [Statbot](https://statbot.net/)
- [ServerStats](https://serverstats.bot/)

### Верификация
- [Captcha.bot](https://captcha.bot/)
- [Verifier Bot](https://verifierbot.xyz/)

### Discord.py документация
- [discord.py Docs](https://discordpy.readthedocs.io/)
- [Discord Developer Portal](https://discord.com/developers/docs)
- [discord.js Guide (patterns)](https://discordjs.guide/)

### Архитектура и паттерны
- [Discord Bot Architecture](https://itsnikhil.medium.com/architecting-discord-bot-the-right-way-46e426a0b995)
- [Discord Components Guide](https://discordjs.guide/interactive-components/buttons)
- [Ephemeral Messages](https://support-apps.discord.com/hc/en-us/articles/26501839512855-Ephemeral-Messages-FAQ)

---

## Заметки для реализации

### Важные лимиты Discord

| Компонент | Лимит |
|-----------|-------|
| Embed title | 256 символов |
| Embed description | 4096 символов |
| Embed fields | 25 полей |
| Embed field name | 256 символов |
| Embed field value | 1024 символа |
| Total embed | 6000 символов |
| Buttons per row | 5 |
| Button rows | 5 |
| Select options | 25 |
| Message content | 2000 символов |
| Interaction response | 3 секунды |
| Timeout max | 28 дней |

### Полезные паттерны

**Ephemeral для игр:**
```python
await interaction.response.send_message(
    embed=game_embed,
    view=game_view,
    ephemeral=True  # Только игрок видит
)
```

**Defer для долгих операций:**
```python
await interaction.response.defer()
# ... долгая операция ...
await interaction.followup.send(result)
```

**Persistent views:**
```python
class PersistentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Никогда не истекает

    @discord.ui.button(custom_id="persistent_button")
    async def button(self, interaction, button):
        ...

# В on_ready:
bot.add_view(PersistentView())
```

**Cooldown:**
```python
from discord.app_commands import cooldown
from discord import app_commands

@app_commands.command()
@app_commands.checks.cooldown(1, 86400)  # 1 раз в 24 часа
async def daily(interaction):
    ...
```

---

*Документ создан: 29.01.2026*
*Версия: 1.0*
