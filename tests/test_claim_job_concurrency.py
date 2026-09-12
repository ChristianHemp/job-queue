import threading

from app.database import SessionLocal
from app.models import JobDB
from app.services import _claim_job


def _make_pending_job(db_session) -> int:
    job = JobDB(job_type="sum_numbers", payload={"numbers": [1, 2, 3]}, priority=2, status="pending")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job.job_id


def test_only_one_concurrent_claim_succeeds(db_session):
    job_id = _make_pending_job(db_session)

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt_claim():
        with SessionLocal() as db:
            barrier.wait()  # force both threads to call _claim_job at the same instant
            claimed = _claim_job(db, job_id)
            results.append(claimed is not None)

    threads = [threading.Thread(target=attempt_claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [False, True]

    db_session.expire_all()
    job = db_session.get(JobDB, job_id)
    assert job.status == "running"


def test_claim_fails_on_already_running_job(db_session):
    job = JobDB(job_type="sum_numbers", payload={"numbers": [1]}, priority=2, status="running")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    with SessionLocal() as db:
        claimed = _claim_job(db, job.job_id)

    assert claimed is None
