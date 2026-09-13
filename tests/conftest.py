# Env vars must be set before any `app.*` import - pytest imports this file
# before collecting test modules, which is what actually guarantees ordering
# (create_engine()/redis.from_url() bind to these at import time).
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://christian@localhost/job_queue_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.queue as queue_module
from app.database import SessionLocal, engine
from app.main import app as fastapi_app
from app.models import Base


@pytest.fixture(scope="session", autouse=True)
def _verify_test_database():
    # Refuse to run against anything that isn't obviously a test database -
    # the per-test fixture below truncates the jobs table.
    db_name = engine.url.database
    assert db_name is not None and db_name.endswith("_test"), (
        f"Refusing to run tests against database {db_name!r} - "
        "DATABASE_URL must point at a database ending in '_test'."
    )
    return db_name


@pytest.fixture(scope="session", autouse=True)
def _create_schema(_verify_test_database):
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_jobs_table(_create_schema):
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE jobs RESTART IDENTITY CASCADE"))
        conn.commit()


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(queue_module, "redis_client", fake)
    return fake


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # `with` form so the lifespan (reconcile_jobs + reclaimer thread) actually runs.
    with TestClient(fastapi_app) as test_client:
        yield test_client
