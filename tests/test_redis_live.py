"""Manual, on-demand sanity check against the real Redis Cloud instance.

Excluded from the default test run (see pytest.ini's `addopts`). Run with:
    pytest -m integration
"""
import pytest
import redis
from dotenv import dotenv_values


@pytest.mark.integration
def test_live_redis_ping_and_round_trip():
    # conftest.py already stomped os.environ["REDIS_URL"] with a dummy value
    # (so normal tests never touch the real instance) - read the real value
    # straight out of .env instead of relying on the environment.
    real_redis_url = dotenv_values().get("REDIS_URL")
    assert real_redis_url is not None, ".env is missing REDIS_URL"

    client = redis.from_url(real_redis_url, decode_responses=True, socket_connect_timeout=5)

    assert client.ping() is True

    test_key = "jobqueue:test_redis_live:probe"
    client.delete(test_key)
    client.zadd(test_key, {"probe-member": 1})
    result = client.zpopmin(test_key, count=1)
    client.delete(test_key)

    assert result == [("probe-member", 1.0)]
