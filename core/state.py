from asyncio import Lock

queue = []
queue_lock = Lock()
current = None
looping = False