from asyncio import Lock
import time

queue = []
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
    last_now_playing_message = None
    is_manual_operation = False
    current_start_time = 0
    elapsed_at_pause = None