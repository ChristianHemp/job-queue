from app.models import JobDB
from app.services import process_job


def _make_job(db_session, status="pending", job_type="sum_numbers", payload=None) -> JobDB:
    job = JobDB(
        job_type=job_type,
        payload=payload if payload is not None else {"numbers": [1, 2, 3]},
        priority=2,
        status=status,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_pending_job_completes_successfully(db_session):
    job = _make_job(db_session, payload={"numbers": [1, 2, 3]})

    process_job(db_session, job.job_id)

    db_session.expire_all()
    updated = db_session.get(JobDB, job.job_id)
    assert updated.status == "completed"
    assert updated.result == 6
    assert updated.error is None


def test_job_marked_failed_when_executor_raises(db_session):
    # sum_numbers expects a list of ints - a bad payload makes the executor raise.
    job = _make_job(db_session, job_type="sum_numbers", payload={"numbers": ["not", "numbers"]})

    process_job(db_session, job.job_id)

    db_session.expire_all()
    updated = db_session.get(JobDB, job.job_id)
    assert updated.status == "failed"
    assert updated.result is None
    assert updated.error is not None


def test_already_running_job_is_skipped_not_reprocessed(db_session):
    job = _make_job(db_session, status="running")

    process_job(db_session, job.job_id)

    db_session.expire_all()
    updated = db_session.get(JobDB, job.job_id)
    # Claim lost (not pending) - process_job should no-op, not overwrite state.
    assert updated.status == "running"
    assert updated.result is None
