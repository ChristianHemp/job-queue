import threading

from sqlalchemy import text

from app.database import SessionLocal
from app.models import JobDB
from app.services import _mark_job_completed, _reclaim_stale_running_jobs, reconcile_jobs


def _make_running_job(db_session, started_seconds_ago: float) -> int:
    job = JobDB(job_type="sum_numbers", payload={"numbers": [1]}, priority=2, status="running")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # Backdate started_at directly via SQL - simpler and more explicit than
    # sleeping in a test to make a row actually go stale.
    db_session.execute(
        text("UPDATE jobs SET started_at = now() - make_interval(secs => :secs) WHERE job_id = :id"),
        {"secs": started_seconds_ago, "id": job.job_id},
    )
    db_session.commit()
    return job.job_id


def test_stale_running_job_is_reclaimed(db_session, monkeypatch):
    monkeypatch.setattr("app.services.JOB_STALE_SECONDS", 5)
    job_id = _make_running_job(db_session, started_seconds_ago=10)

    _reclaim_stale_running_jobs(db_session)

    db_session.expire_all()
    job = db_session.get(JobDB, job_id)
    assert job.status == "pending"
    assert job.started_at is None
    assert job.reclaim_count == 1

    from app.queue import redis_client
    assert redis_client.zscore("jobqueue:jobs", str(job_id)) is not None


def test_fresh_running_job_is_left_untouched(db_session, monkeypatch):
    monkeypatch.setattr("app.services.JOB_STALE_SECONDS", 60)
    job_id = _make_running_job(db_session, started_seconds_ago=5)

    _reclaim_stale_running_jobs(db_session)

    db_session.expire_all()
    job = db_session.get(JobDB, job_id)
    assert job.status == "running"
    assert job.reclaim_count == 0


def test_reconcile_jobs_handles_pending_and_stale_running_together(db_session, monkeypatch):
    monkeypatch.setattr("app.services.JOB_STALE_SECONDS", 5)

    pending_job = JobDB(job_type="sum_numbers", payload={"numbers": [1]}, priority=2, status="pending")
    db_session.add(pending_job)
    db_session.commit()
    db_session.refresh(pending_job)

    stale_job_id = _make_running_job(db_session, started_seconds_ago=10)

    reconcile_jobs(db_session)

    from app.queue import redis_client
    assert redis_client.zscore("jobqueue:jobs", str(pending_job.job_id)) is not None
    assert redis_client.zscore("jobqueue:jobs", str(stale_job_id)) is not None


def test_hardened_mark_completed_cannot_clobber_a_reclaim(db_session):
    # Simulates the exact window this hardening protects: a job gets
    # reclaimed (flipped RUNNING -> PENDING because it looked stale) before
    # anyone has re-claimed it, and the original (slow-but-alive) worker's
    # completion write arrives during that window. It must be dropped, not
    # applied - otherwise a stale write could resurrect a job that's now
    # legitimately waiting to be picked up again.
    job = JobDB(job_type="sum_numbers", payload={"numbers": [1]}, priority=2, status="running")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    job_id = job.job_id

    # The reclaimer flips it back to PENDING - nothing has re-claimed it yet.
    with SessionLocal() as other_db:
        other_db.execute(
            text("UPDATE jobs SET status = 'pending', started_at = NULL, "
                 "reclaim_count = reclaim_count + 1 WHERE job_id = :id"),
            {"id": job_id},
        )
        other_db.commit()

    # The original caller's completion write should be dropped, not applied,
    # because it's conditional on status still being RUNNING.
    wrote = _mark_job_completed(db_session, job_id, result=999)

    assert wrote is False

    db_session.expire_all()
    reloaded = db_session.get(JobDB, job_id)
    assert reloaded.status == "pending"
    assert reloaded.result is None
