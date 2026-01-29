# Проблемы проекта AstraBot

## КРИТИЧНЫЕ

### 1. ~~Deadlock в player.py:97-98~~
**Статус:** [x] Проанализировано - не является deadlock'ом (callback вызывается после освобождения lock)

### 2. ~~Неправильное использование asyncio в queue_manager.py~~
**Файл:** `core/queue_manager.py`
**Проблема:** `asyncio.run_coroutine_threadsafe()` вызывался внутри async функции
**Статус:** [x] Исправлено - заменено на `asyncio.create_task()`

### 3. ~~pending_queue не очищается при /leave~~
**Файл:** `commands/utility/leave.py`, `ui/controls.py`
**Статус:** [x] Исправлено - добавлена очистка `state.pending_queue.clear()`

---

## СРЕДНИЕ

### 4. ~~Закомментированный мертвый код~~
**Файлы:**
- `core/queue_manager.py:185-218`
- `ui/controls.py:123-128`
**Статус:** [x] Удалено

### 5. ~~Дублирование ThreadPoolExecutor~~
**Статус:** [x] Исправлено - вынесен в `core/state.py` как общий `executor`

### 6. ~~Дублирование ydl_opts~~
**Статус:** [x] Исправлено - вынесен в константу `YDL_OPTS` в `utils/yt_utils.py`

### 7. ~~Множественные вызовы logging.basicConfig()~~
**Статус:** [x] Исправлено - убрано из модулей, настроен root logger в `bot.py`

### 8. Неполный reset_playback_state()
**Файл:** `core/state.py`
**Статус:** [ ] Оставлено как есть - очистка очереди должна быть явной

### 9. ~~Источник Spotify показывается как YouTube~~
**Файл:** `ui/controls.py`
**Статус:** [x] Исправлено - добавлена корректная логика определения источника

---

## МЕЛКИЕ

### 10. Потенциальный NoneType в bot.py:129
**Статус:** [x] Проанализировано - не является проблемой (в событии всегда есть хотя бы один канал)

### 11. ~~print() вместо logger~~
**Файлы:** `cogs/ticket_system/views.py`
**Статус:** [x] Исправлено - заменено на `logger.error()` и `logger.warning()`

---

## УЛУЧШЕНИЯ (опционально)

- [ ] Добавить /volume для регулировки громкости
- [ ] Добавить кнопку повтора обратно
- [ ] Добавить /remove [номер] для удаления из очереди

---

## Исправленные файлы

1. `core/queue_manager.py` - удален мертвый код, исправлен asyncio
2. `core/player.py` - убран дублирующийся executor и logging.basicConfig
3. `core/state.py` - добавлен общий executor
4. `ui/controls.py` - удален мертвый код, исправлено отображение Spotify, очистка pending_queue
5. `utils/yt_utils.py` - вынесены YDL_OPTS в константу, убран logging.basicConfig
6. `commands/utility/leave.py` - добавлена очистка pending_queue
7. `cogs/ticket_system/views.py` - заменены print на logger
8. `bot.py` - настроен root logger
