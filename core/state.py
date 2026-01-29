from asyncio import Lock
from concurrent.futures import ThreadPoolExecutor
import time

# Общий executor для всех модулей
executor = ThreadPoolExecutor(max_workers=4)

queue = []
pending_queue = []
queue_lock = Lock()
current = None
looping = False

last_now_playing_message = None
is_manual_operation = False
current_start_time = 0
elapsed_at_pause = None
       
def reset_playback_state():
    global current, last_now_playing_message, is_manual_operation, current_start_time, elapsed_at_pause
    current = None
    is_manual_operation = False
    current_start_time = 0
    elapsed_at_pause = None

def full_reset():
    """Полный сброс состояния (при старте бота)"""
    global queue, pending_queue, current, looping, last_now_playing_message
    global is_manual_operation, current_start_time, elapsed_at_pause
    queue.clear()
    pending_queue.clear()
    current = None
    looping = False
    last_now_playing_message = None
    is_manual_operation = False
    current_start_time = 0
    elapsed_at_pause = None
    idle_since.clear()
    last_text_channels.clear()

idle_since = {}
last_text_channels = {}