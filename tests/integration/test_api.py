"""HTTP surface."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from wardrobe.pipeline import orchestrator as orchestrator_module
from wardrobe.vrm.build import BodyProportions, build_vrm


@pytest.fixture
def client(orchestrator, monkeypatch):
    """A TestClient wired to the temp-storage orchestrator from conftest."""
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    with TestClient(app) as test_client:
        yield test_client


def create_job(client: TestClient, storage_key: str, prompt: str, **overrides) -> dict:
    payload = {
        "avatar": {"storageKey": storage_key, "avatarId": "mira"},
        "outfit": {"prompt": prompt, "mode": "template"},
        "options": {"renderPreview": False, "engine": "native", "wardrobeId": "mira"},
    }
    payload.update(overrides)
    response = client.post("/v1/jobs", json=payload)
    return response


# ----------------------------------------------------------------------
# service
# ----------------------------------------------------------------------
def test_health(client: TestClient):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["service"] == "3D-Wardrobe-Forge"


def test_capabilities_reports_the_engine_and_library(client: TestClient):
    body = client.get("/v1/capabilities").json()
    assert body["engines"]["native"] is True
    assert body["templates"] >= 12
    assert "dress" in body["categories"]


def test_openapi_is_served(client: TestClient):
    schema = client.get("/openapi.json").json()
    assert "/v1/jobs" in schema["paths"]


# ----------------------------------------------------------------------
# templates
# ----------------------------------------------------------------------
def test_list_templates(client: TestClient):
    templates = client.get("/v1/templates").json()
    assert len(templates) >= 12
    assert {"id", "category", "coverage", "fit"} <= set(templates[0])


def test_filter_templates_by_category(client: TestClient):
    dresses = client.get("/v1/templates?category=dress").json()
    assert dresses and all(item["category"] == "dress" for item in dresses)


def test_a_category_names_its_recommended_template(client: TestClient):
    """S3. The Studio labels "Planner chooses" with it, so the default must reach the browser."""
    skirts = client.get("/v1/templates?category=skirt").json()
    assert [item["id"] for item in skirts if item["defaultForCategory"]] == ["skirt-a-line-v1"]


def test_unknown_template_is_404(client: TestClient):
    assert client.get("/v1/templates/nope").status_code == 404


# ----------------------------------------------------------------------
# avatars
# ----------------------------------------------------------------------
def test_inspect_avatar(client: TestClient, vrm_bytes: bytes):
    response = client.post(
        "/v1/avatars/inspect", files={"file": ("a.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["usable"] is True
    assert body["analysis"]["spec"] == "VRM1"
    assert body["license"]["allowed"] is True


def test_inspect_rejects_a_non_vrm(client: TestClient):
    response = client.post(
        "/v1/avatars/inspect", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "source_is_not_a_vrm"


def test_inspect_reports_a_locked_model(client: TestClient):
    data = build_vrm(BodyProportions(name="locked", modification="prohibited"), spec="VRM1")
    body = client.post(
        "/v1/avatars/inspect", files={"file": ("a.vrm", io.BytesIO(data), "model/gltf-binary")}
    ).json()

    assert body["license"]["allowed"] is False
    assert body["license"]["reason"] == "source_model_modification_not_permitted"


def test_upload_returns_a_storage_key(client: TestClient, vrm_bytes: bytes):
    response = client.post(
        "/v1/avatars", files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    )
    body = response.json()

    assert response.status_code == 201
    assert body["storageKey"].startswith("sources/")
    assert len(body["sha256"]) == 64


# ----------------------------------------------------------------------
# jobs
# ----------------------------------------------------------------------
def test_create_job_is_accepted(client: TestClient, vrm_bytes: bytes):
    upload = client.post(
        "/v1/avatars", files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    ).json()

    response = create_job(client, upload["storageKey"], "elegant burgundy evening dress")
    assert response.status_code == 202

    job = response.json()
    assert job["state"] == "queued"
    assert job["id"].startswith("job_")


def test_job_runs_to_completion(client: TestClient, vrm_bytes: bytes):
    upload = client.post(
        "/v1/avatars", files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    ).json()
    job = create_job(client, upload["storageKey"], "black satin cocktail dress").json()

    final = _wait(client, job["id"])
    assert final["state"] == "completed"
    assert final["look"]["vrmUrl"]
    assert final["fitReport"]["vrmValid"] is True
    assert final["fitReport"]["humanoidValid"] is True
    assert final["fitReport"]["weightsValid"] is True


def test_generated_vrm_is_downloadable(client: TestClient, vrm_bytes: bytes):
    upload = client.post(
        "/v1/avatars", files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    ).json()
    job = create_job(client, upload["storageKey"], "a long red dress").json()
    final = _wait(client, job["id"])

    response = client.get(final["look"]["vrmUrl"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.content[:4] == b"glTF"


def test_unknown_job_is_404(client: TestClient):
    assert client.get("/v1/jobs/job_missing").status_code == 404


def test_invalid_request_is_422(client: TestClient):
    # Neither url nor storageKey supplied.
    response = client.post(
        "/v1/jobs", json={"avatar": {}, "outfit": {"prompt": "a dress"}}
    )
    assert response.status_code == 422


def test_asset_path_traversal_is_refused(client: TestClient):
    assert client.get("/v1/assets/../../etc/passwd").status_code == 404


# ----------------------------------------------------------------------
# wardrobes
# ----------------------------------------------------------------------
def test_wardrobe_is_built_and_rendered_for_the_chatbot(client: TestClient, vrm_bytes: bytes):
    upload = client.post(
        "/v1/avatars", files={"file": ("mira.vrm", io.BytesIO(vrm_bytes), "model/gltf-binary")}
    ).json()
    job = create_job(client, upload["storageKey"], "a burgundy evening dress").json()
    _wait(client, job["id"])

    wardrobe = client.get("/v1/wardrobes/mira").json()
    assert wardrobe["avatarId"] == "mira"
    assert any(look["type"] == "vrmVariant" for look in wardrobe["looks"])

    manifest = client.get("/v1/wardrobes/mira/avatars.json").json()
    assert manifest["items"]
    assert {"name", "file", "url", "format"} <= set(manifest["items"][0])


def test_unknown_wardrobe_is_404(client: TestClient):
    assert client.get("/v1/wardrobes/nobody").status_code == 404


def _wait(client: TestClient, job_id: str, attempts: int = 400) -> dict:
    """TestClient runs the app's event loop, so poll rather than sleep."""
    for _ in range(attempts):
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["state"] in {"completed", "failed", "rejected"}:
            return job
    raise AssertionError(f"job {job_id} did not finish")
