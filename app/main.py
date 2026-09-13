import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import SessionLocal
from app.logging_config import configure_logging
from app.routes import router
from app.services import reconcile_jobs

configure_logging()
logger = logging.getLogger(__name__)

# How often the background reclaimer sweeps for PENDING jobs missing from
# Redis and RUNNING jobs whose worker appears to have died. Kept well above
# any test's own duration so it never fires mid-test-run (see tests/conftest.py).
RECLAIM_INTERVAL_SECONDS = int(os.environ.get("RECLAIM_INTERVAL_SECONDS", 30))


def _reclaim_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(timeout=RECLAIM_INTERVAL_SECONDS):
        with SessionLocal() as db:
            reconcile_jobs(db)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Reconcile Postgres -> Redis once immediately at startup (e.g. jobs
    # PENDING or stuck RUNNING from a prior crash), then keep sweeping
    # periodically via a background thread. This thread only ever does a
    # DB-only sweep (conditional UPDATE + enqueue) - unlike the worker
    # thread removed earlier, it never claims or executes jobs itself, so it
    # doesn't compete with the scalable `worker` processes for work.
    with SessionLocal() as db:
        reconcile_jobs(db)

    stop_event = threading.Event()
    reclaimer_thread = threading.Thread(target=_reclaim_loop, args=(stop_event,), daemon=True)
    reclaimer_thread.start()

    yield

    stop_event.set()
    reclaimer_thread.join(timeout=5)

app = FastAPI(lifespan=app_lifespan)

app.include_router(router)
