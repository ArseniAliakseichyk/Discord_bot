"""
Модальные окна для конструктора embed.
"""

from .main_modals import MainSettingsModal, ContentModal
from .author_footer import AuthorModal, FooterModal
from .field_modals import FieldModal
from .image_modals import ImageModal
from .schedule_modal import ScheduleModal
from .thread_modal import ThreadNameModal

__all__ = [
    'MainSettingsModal',
    'ContentModal',
    'AuthorModal',
    'FooterModal',
    'FieldModal',
    'ImageModal',
    'ScheduleModal',
    'ThreadNameModal',
]
