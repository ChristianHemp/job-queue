import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://christian@localhost/job_queue")

# Each worker process only ever holds one session at a time in its
# sequential loop, so the launcher (scripts/run_workers.py) sets these lower
# per-process to keep total connections bounded as worker count grows,
# instead of relying on the default pool_size=5/max_overflow=10 headroom.
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", 5))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", 10))

engine = create_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()