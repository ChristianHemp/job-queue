from queue import PriorityQueue
from itertools import count

job_queue = PriorityQueue()
counter = count()

def enqueue(job_id: int, job_priority: int) -> None:
    job_queue.put((job_priority, next(counter), job_id))

def dequeue() -> int:
    _, _, job_id = job_queue.get()
    return job_id