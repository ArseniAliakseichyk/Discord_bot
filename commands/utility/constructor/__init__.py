"""
Модульный конструктор embed-сообщений.

Структура:
- command.py: Slash-команда /constructor
- views/: UI компоненты (Views, Buttons, Selects)
- modals/: Модальные окна для ввода данных
- utils/: Вспомогательные функции (цвета, валидация, шаблоны)
- constants.py: Константы и лимиты Discord
"""

from .command import constructor, schedule_cancel, schedule_list

__all__ = ['constructor', 'schedule_cancel', 'schedule_list']
