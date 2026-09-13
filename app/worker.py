import logging

from app.database import SessionLocal
from app.logging_config import configure_logging
from app.queue import dequeue
from app.services import process_job

logger = logging.getLogger(__name__)


def run_worker():
    logger.info("worker started", extra={"event": "worker_started", "job_id": None})

    while True:
        job_id = dequeue()
        logger.info(f"job {job_id}: dequeued", extra={"event": "job_dequeued", "job_id": job_id})

        # Worker needs its own db session, does not operate under FastAPI Depends(get_db) route logic
        with SessionLocal() as db:
            process_job(db, job_id)


if __name__ == "__main__":
    configure_logging()
    run_worker()
