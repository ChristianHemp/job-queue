# job-queue

A small FastAPI job queue backed by Postgres (durable job state) and Redis (the work queue),
with support for multiple worker processes.

## Running with Docker Compose

```bash
docker compose up
```

This starts Postgres, the API, and a worker together automatically. The API is available at
http://localhost:8000, with interactive docs (Swagger UI) at http://localhost:8000/docs.

Scale workers with:

```bash
docker compose up --scale worker=3
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
test hits the real Redis instance and is excluded by default; run it with `pytest -m integration`.
