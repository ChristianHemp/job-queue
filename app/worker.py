import os
from datetime import datetime

from app.database import SessionLocal
from app.queue import dequeue
from app.services import process_job


def run_worker():
    print(f"[pid={os.getpid()}] worker started")

    while True:
        job_id = dequeue()
        print(f"[pid={os.getpid()}] {datetime.now().isoformat(timespec='seconds')} job {job_id}: dequeued")

        # Worker needs its own db session, does not operate under FastAPI Depends(get_db) route logic
        with SessionLocal() as db:
            process_job(db, job_id)


if __name__ == "__main__":
    run_worker()