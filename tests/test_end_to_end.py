from app.queue import dequeue
from app.services import process_job


def test_submit_dequeue_process_full_loop(client, db_session):
    response = client.post(
        "/jobs",
        json={"job_type": "sum_numbers", "priority": 1, "payload": {"numbers": [4, 5, 6]}},
    )
    job_id = response.json()["job_id"]

    # No worker process running - drain the queue and process the job directly,
    # exactly like `app/worker.py`'s loop does.
    dequeued_id = dequeue()
    assert dequeued_id == job_id

    process_job(db_session, job_id)

    final = client.get(f"/jobs/{job_id}")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "completed"
    assert body["result"] == 15
