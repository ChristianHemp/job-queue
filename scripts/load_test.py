#!/usr/bin/env python3
"""Load-test the job queue API and report real throughput/latency numbers.

Submits a batch of jobs, polls until they all reach a terminal state, and
reports:
  - whole-batch elapsed time + throughput (jobs/sec) - this script's own
    wall-clock, since it's inherently a client-experienced number.
  - p50/p95 latency (completed_at - created_at), broken out per job_type -
    read from the DB-backed timestamps the API returns, not this script's
    own clock, so poll-interval noise and cross-process clock skew never
    enter the number.

Usage:
    python scripts/load_test.py --count 30 --workers-label "1 worker"
    python scripts/load_test.py --count 30 --workers-label "3 workers"

For the resilience scenario: start this against a bigger batch, then in
another terminal run `docker kill <a worker container>` mid-run. This script
just keeps polling - it doesn't need to know a worker died. Success is
"N/N jobs reached completed with no API restart", plus check `reclaim_count`
on the affected job(s) via GET /jobs/{id} as direct proof of recovery.
"""
import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
LARGE_CSV_PATH = "test_data/sales_data_large.csv"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return sorted_values[index]


def _build_job_payload(i: int) -> dict:
    # ~80% fast sum_numbers, ~20% slower analyze_sales_data, so a batch has a
    # real mix instead of one uniform job type.
    if i % 5 == 0:
        return {
            "job_type": "analyze_sales_data",
            "priority": 2,
            "payload": {"file_path": LARGE_CSV_PATH},
        }
    return {
        "job_type": "sum_numbers",
        "priority": 2,
        "payload": {"numbers": [random.randint(1, 100) for _ in range(5)]},
    }


def submit_jobs(client: httpx.Client, count: int, concurrency: int) -> list[int]:
    def _submit(i: int) -> int:
        response = client.post("/jobs", json=_build_job_payload(i))
        response.raise_for_status()
        return response.json()["job_id"]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(_submit, range(count)))


def poll_until_done(
    client: httpx.Client, job_ids: list[int], poll_interval: float, max_wait: float
) -> dict[int, dict]:
    results: dict[int, dict] = {}
    remaining = set(job_ids)
    deadline = time.monotonic() + max_wait

    def _check(job_id: int) -> dict | None:
        response = client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        return None

    with ThreadPoolExecutor(max_workers=min(32, len(job_ids) or 1)) as pool:
        while remaining and time.monotonic() < deadline:
            checked = dict(zip(remaining, pool.map(_check, remaining)))
            for job_id, body in checked.items():
                if body is not None:
                    results[job_id] = body
                    remaining.discard(job_id)

            if remaining:
                time.sleep(poll_interval)

    if remaining:
        print(f"WARNING: {len(remaining)} job(s) never reached a terminal state: {sorted(remaining)}")

    return results


def report(results: dict[int, dict], elapsed: float, label: str) -> None:
    completed = [r for r in results.values() if r["status"] == "completed"]
    failed = [r for r in results.values() if r["status"] == "failed"]

    print(f"\n=== {label} ===")
    print(f"submitted: {len(results) + 0}, completed: {len(completed)}, failed: {len(failed)}")
    print(f"batch elapsed: {elapsed:.2f}s")
    print(f"throughput: {len(results) / elapsed:.2f} jobs/sec")

    latencies_by_type: dict[str, list[float]] = {}
    reclaimed = []
    for r in completed:
        created = _parse_iso(r["created_at"])
        finished = _parse_iso(r["completed_at"])
        latency = (finished - created).total_seconds()
        latencies_by_type.setdefault(r["job_type"], []).append(latency)
        if r.get("reclaim_count", 0) > 0:
            reclaimed.append(r["job_id"])

    for job_type, latencies in latencies_by_type.items():
        latencies.sort()
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        print(f"  {job_type}: n={len(latencies)}  p50={p50 * 1000:.1f}ms  p95={p95 * 1000:.1f}ms")

    if reclaimed:
        print(f"resilience: {len(reclaimed)} job(s) recovered via reclaim: {reclaimed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load-test the job queue API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--count", type=int, default=30, help="number of jobs to submit")
    parser.add_argument("--submit-concurrency", type=int, default=10)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-wait", type=float, default=120.0)
    parser.add_argument("--label", default="load test", help="label for this run's report")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        start = time.monotonic()
        job_ids = submit_jobs(client, args.count, args.submit_concurrency)
        results = poll_until_done(client, job_ids, args.poll_interval, args.max_wait)
        elapsed = time.monotonic() - start

    report(results, elapsed, args.label)


if __name__ == "__main__":
    main()
