from app.database import SessionLocal
from app.job_queue import dequeue
from app.services import process_job


def run_worker():
    while True:
        job_id = dequeue()

        with SessionLocal() as db:
            process_job(db, job_id)