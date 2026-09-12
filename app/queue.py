import os
import time

import redis
from dotenv import load_dotenv

load_dotenv()

_QUEUE_KEY = "jobqueue:jobs"
_COUNTER_KEY = "jobqueue:counter"

# Must exceed any realistic counter value so priority always dominates
# FIFO ordering within a tier.
_PRIORITY_MULTIPLIER = 1_000_000

# This managed/proxied Redis instance kills a blocking BZPOPMIN read after
# ~5s regardless of the requested timeout (a socket TimeoutError, not a nil
# reply), so a true server-side block isn't reliable here. Poll with a
# non-blocking ZPOPMIN and sleep client-side between empty checks instead.
_POLL_INTERVAL_SECONDS = 0.5

redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

def enqueue(job_id: int, job_priority: int) -> None:
    counter = redis_client.incr(_COUNTER_KEY)
    score = job_priority * _PRIORITY_MULTIPLIER + counter
    redis_client.zadd(_QUEUE_KEY, {str(job_id): score})

def dequeue() -> int:
    while True:
        result = redis_client.zpopmin(_QUEUE_KEY, count=1)
        if result:
            job_id, _ = result[0]
            return int(job_id)
        time.sleep(_POLL_INTERVAL_SECONDS)
