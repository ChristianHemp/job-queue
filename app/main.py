from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.routes import router
from app.database import engine
from app.models import Base
from app.services import restore_pending_jobs


# Create database tables if missing
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Reconcile Postgres -> Redis: re-enqueue any jobs still PENDING (e.g. from
    # a prior crash). Workers now run as separate processes (`python -m
    # app.worker`) started explicitly - the API no longer runs one itself.
    restore_pending_jobs()

    yield

app = FastAPI(lifespan=app_lifespan)

app.include_router(router)