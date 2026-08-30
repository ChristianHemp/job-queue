from app.database import SessionLocal
from app.queue import dequeue
from app.services import process_job


def run_worker():
    while True:
        job_id = dequeue()

        # Worker thread needs its own db session, does not operate under FastAPI Depends(get_db) route logic
        with SessionLocal() as db:
            process_job(db, job_id)