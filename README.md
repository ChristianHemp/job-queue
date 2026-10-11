# job-queue

A small FastAPI job queue backed by Postgres (durable job state) and Redis (the work queue),
with support for multiple worker processes.

## Running with Docker Compose

```bash
docker compose up
```

This starts Postgres, Redis, the API, and a worker together automatically. The API is available at
http://localhost:8000, with interactive docs (Swagger UI) at http://localhost:8000/docs.

Scale workers with:

```bash
docker compose up --scale worker=3
```

## Running locally without Docker

Useful for active development, e.g. with `--reload`.

Prerequisites: a local Postgres server and a Redis server running, and a `.env` file with
`REDIS_URL` set (see `.env.example`) — `DATABASE_URL` defaults to a local `job_queue` database
if not set.

The simplest way to get Redis is to start just the Compose service, which listens on
`localhost:6379`:

```bash
docker compose up -d redis
```

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

createdb job_queue    # first time only
alembic upgrade head  # applies schema migrations
```

Start the API, with auto-reload on code changes:

```bash
uvicorn app.main:app --reload
```

The API on its own does not process any jobs — it only accepts and stores them. In a **separate
terminal**, start a worker to actually run them:

```bash
python -m app.worker
```

To run multiple workers at once instead of one:

```bash
python scripts/run_workers.py --count 3
```

## API examples

### Create a `sum_numbers` job

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
        "job_type": "sum_numbers",
        "priority": 2,
        "payload": {"numbers": [1, 2, 3, 4, 5]}
      }'
```

### Create an `analyze_sales_data` job

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
        "job_type": "analyze_sales_data",
        "priority": 2,
        "payload": {"file_path": "test_data/test_sales_data.csv"}
      }'
```

### Get a job by ID

```bash
curl http://localhost:8000/jobs/1
```

### List all jobs

```bash
curl http://localhost:8000/jobs
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Requires a local `job_queue_test` Postgres database (`createdb job_queue_test`) — the suite
uses `fakeredis` for the queue, so no live Redis connection is needed to run it. One additional
test hits the real Redis instance and is excluded by default; run it with `pytest -m integration`. Redis transitioned from redis cloud to local Redis due to maintinence issues.