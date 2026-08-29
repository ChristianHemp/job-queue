from fastapi import FastAPI
from contextlib import asynccontextmanager
from threading import Thread

from app.routes import router
from app.worker import run_worker
from app.database import engine
from app.models import Base


Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    worker_thread = Thread(target=run_worker, daemon=True)

    worker_thread.start()

    yield

app = FastAPI(lifespan=app_lifespan)

app.include_router(router)