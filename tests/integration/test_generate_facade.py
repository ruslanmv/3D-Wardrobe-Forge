from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from wardrobe.pipeline import orchestrator as orchestrator_module


@pytest.fixture
def client(orchestrator, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    with TestClient(app) as test_client:
        yield test_client


def test_generate_facade_delegates_to_job_pipeline(client: TestClient, vrm_bytes: bytes):
    upload = client.post(
        "/v1/avatars",
        files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")},
    ).json()

    response = client.post(
        "/v1/generate",
        json={
            "avatar": {"storageKey": upload["storageKey"], "avatarId": "mira"},
            "prompt": "black satin cocktail dress",
            "mode": "template",
            "options": {
                "renderPreview": False,
                "engine": "native",
                "wardrobeId": "mira",
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["jobId"].startswith("job_")
    assert body["status"] == "queued"
    assert body["statusUrl"] == f"/v1/jobs/{body['jobId']}"
    assert body["eventsUrl"].endswith("/events")


def test_generate_facade_is_in_openapi(client: TestClient):
    assert "/v1/generate" in client.get("/openapi.json").json()["paths"]
