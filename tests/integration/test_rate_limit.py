"""F1. The job-creation limit: on the routes that start a fit, never on a read, off by default.

A Try-On haul polls its job every second or so; if reads counted, the limit meant
for a visitor queueing fifty fits would refuse the one visitor doing it right. And
a deployment that never set the limit must behave exactly as before it existed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import ratelimit
from apps.api.dependencies import orchestrator_dependency, settings_dependency
from apps.api.main import app
from tests.conftest import job_request
from wardrobe.config import Settings
from wardrobe.domain.jobs import CreateJobRequest, JobRecord


class QueueOnly:
    """Accepts jobs and never runs them: every job stays queued, as on a busy Space."""

    def __init__(self, catalog) -> None:
        self.records: list[JobRecord] = []
        self.catalog = catalog

    async def submit(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord.queued(request)
        self.records.insert(0, record)
        return record

    async def list(self, *, limit: int = 50) -> list[JobRecord]:
        return self.records[:limit]

    async def get(self, job_id: str) -> JobRecord | None:
        return next((r for r in self.records if r.id == job_id), None)


@pytest.fixture
def api(tmp_path, template_catalog):
    queue = QueueOnly(template_catalog)
    current = {"settings": Settings(_env_file=None, wardrobe_storage_root=str(tmp_path))}
    app.dependency_overrides[settings_dependency] = lambda: current["settings"]
    app.dependency_overrides[orchestrator_dependency] = lambda: queue
    ratelimit.window.reset()

    def configure(**fields):
        current["settings"] = Settings(_env_file=None, wardrobe_storage_root=str(tmp_path), **fields)

    try:
        yield TestClient(app), configure, queue
    finally:
        app.dependency_overrides.pop(settings_dependency, None)
        app.dependency_overrides.pop(orchestrator_dependency, None)
        ratelimit.window.reset()


def create(client, address="203.0.113.7", **headers):
    return client.post("/v1/jobs", json=job_request("sources/a.vrm", "black crop top"),
                       headers={"X-Forwarded-For": address, **headers})


def test_off_by_default(api):
    client, _, _ = api
    assert all(create(client).status_code == 202 for _ in range(12))


def test_a_client_is_limited_and_told_when_to_retry(api):
    client, configure, _ = api
    configure(wardrobe_rate_limit_per_minute=3, wardrobe_forwarded_hops=1)
    assert [create(client).status_code for _ in range(3)] == [202, 202, 202]
    refused = create(client)
    assert refused.status_code == 429
    assert refused.json()["detail"]["reason"] == "rate_limited"
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    # Another visitor is not held up by the first.
    assert create(client, address="198.51.100.4").status_code == 202


def test_generate_counts_as_job_creation(api):
    client, configure, _ = api
    configure(wardrobe_rate_limit_per_minute=1, wardrobe_forwarded_hops=1)
    headers = {"X-Forwarded-For": "203.0.113.9"}
    body = {"avatar": job_request("sources/a.vrm", "x")["avatar"], "prompt": "black crop top"}
    assert client.post("/v1/generate", json=body, headers=headers).status_code == 202
    assert client.post("/v1/generate", json=body, headers=headers).status_code == 429


def test_reads_are_never_limited(api):
    client, configure, queue = api
    configure(wardrobe_rate_limit_per_minute=1, wardrobe_queue_cap=1, wardrobe_forwarded_hops=1)
    job = create(client).json()
    assert create(client).status_code == 429
    for _ in range(20):
        assert client.get(f"/v1/jobs/{job['id']}", headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 200
    assert client.get("/v1/templates").status_code == 200


def test_the_queue_cap_holds_for_every_client(api):
    client, configure, _ = api
    configure(wardrobe_queue_cap=2, wardrobe_forwarded_hops=1)
    assert create(client, address="192.0.2.1").status_code == 202
    assert create(client, address="192.0.2.2").status_code == 202
    busy = create(client, address="192.0.2.3")
    assert busy.status_code == 429 and busy.headers["Retry-After"] == str(ratelimit.QUEUE_RETRY_S)


def test_the_caller_cannot_choose_its_own_address(api):
    """Only the hop the proxy appended counts; a caller writing X-Forwarded-For writes the left."""
    client, configure, _ = api
    configure(wardrobe_rate_limit_per_minute=1, wardrobe_forwarded_hops=1)
    assert create(client, address="10.0.0.1, 203.0.113.50").status_code == 202
    assert create(client, address="10.0.0.2, 203.0.113.50").status_code == 429


def test_the_window_slides():
    now = [0.0]
    window = ratelimit.SlidingWindow(clock=lambda: now[0])
    assert window.take("a", 2) == 0 and window.take("a", 2) == 0
    assert window.take("a", 2) == pytest.approx(60.0)
    now[0] = 59.0
    assert window.take("a", 2) == pytest.approx(1.0)
    now[0] = 60.0
    assert window.take("a", 2) == 0
