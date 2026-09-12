def test_create_job_persists_and_enqueues(client):
    response = client.post(
        "/jobs",
        json={"job_type": "sum_numbers", "priority": 1, "payload": {"numbers": [1, 2, 3]}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["job_id"] is not None

    from app.queue import redis_client

    assert redis_client.zcard("jobqueue:jobs") == 1


def test_create_job_rejects_unknown_job_type(client):
    response = client.post(
        "/jobs",
        json={"job_type": "not_a_real_type", "priority": 1, "payload": {}},
    )

    assert response.status_code == 422


def test_create_job_rejects_payload_mismatched_with_job_type(client):
    # sum_numbers requires payload.numbers - omitting it should fail validation.
    response = client.post(
        "/jobs",
        json={"job_type": "sum_numbers", "priority": 1, "payload": {}},
    )

    assert response.status_code == 422


def test_get_job_returns_404_when_missing(client):
    response = client.get("/jobs/999999")

    assert response.status_code == 404


def test_get_all_jobs_lists_created_jobs(client):
    client.post("/jobs", json={"job_type": "sum_numbers", "priority": 2, "payload": {"numbers": [1]}})
    client.post("/jobs", json={"job_type": "sum_numbers", "priority": 2, "payload": {"numbers": [2]}})

    response = client.get("/jobs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
