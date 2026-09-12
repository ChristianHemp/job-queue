#!/usr/bin/env python3
"""Launch N `python -m app.worker` processes and interleave their output.

Used to demonstrate/stress-test that the Redis-backed queue (app/queue.py)
is safe under real concurrent consumers - see the plan file's "Immediate
step 2" for the verification procedure.
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _stream_output(proc: subprocess.Popen, shutting_down: threading.Event) -> None:
    for line in proc.stdout:
        print(f"[proc pid={proc.pid}] {line}", end="")

    proc.wait()

    if not shutting_down.is_set() and proc.returncode != 0:
        print(f"[launcher] WARNING: worker pid={proc.pid} exited unexpectedly (code {proc.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multiple app.worker processes concurrently.")
    parser.add_argument("--count", type=int, default=3, help="number of worker processes to start")
    args = parser.parse_args()

    env = {
        **os.environ,
        # Without this, piped (non-tty) stdout is block-buffered and log
        # lines only appear when a worker exits - defeating the point of
        # watching live interleaving across workers.
        "PYTHONUNBUFFERED": "1",
        # Each worker only ever holds one DB session at a time; keep the
        # per-process pool small so N workers don't eat into Postgres's
        # connection limit by accident as N grows.
        "DB_POOL_SIZE": "2",
        "DB_MAX_OVERFLOW": "0",
    }

    shutting_down = threading.Event()
    procs: list[subprocess.Popen] = []
    threads: list[threading.Thread] = []

    for _ in range(args.count):
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        procs.append(proc)

        thread = threading.Thread(target=_stream_output, args=(proc, shutting_down), daemon=True)
        thread.start()
        threads.append(thread)

    print(f"[launcher] started {len(procs)} worker process(es): pids={[p.pid for p in procs]}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[launcher] shutting down workers...")
        shutting_down.set()

        for proc in procs:
            proc.terminate()

        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    for thread in threads:
        thread.join(timeout=1)


if __name__ == "__main__":
    main()
