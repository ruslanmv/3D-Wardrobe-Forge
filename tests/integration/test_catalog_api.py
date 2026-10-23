"""Public garment catalog, cached thumbnails, and customize facade."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from apps.api.routes import catalog as catalog_routes
from wardrobe.domain.jobs import JobState


def test_public_catalog_is_grouped_and_does_not_advertise_fake_previews(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", tmp_path)
    response = client.get("/v1/catalog/garments")
    assert response.status_code == 200
    data = response.json()
    assert data["schemaVersion"] == 1
    assert data["totalTemplates"] >= 12
    assert data["visibleCount"] == sum(g["count"] for g in data["categories"])
    assert data["previewCount"] == 0
    assert all(not item["requiresAdult"]
               for group in data["categories"] for item in group["garments"])
    assert all(item["previewStatus"] == "pending" and item["previewUrl"] is None
               for group in data["categories"] for item in group["garments"])


def test_group_filter_and_restricted_metadata_gate(client):
    tops = client.get("/v1/catalog/garments?category=top")
    assert tops.status_code == 200
    groups = tops.json()["categories"]
    assert groups and all(g["id"] == "top" for g in groups)
    assert client.get("/v1/catalog/garments?category=unknown").status_code == 422
    assert client.get("/v1/catalog/garments?includeRestricted=true").status_code == 403


def test_preview_is_only_served_when_real_webp_exists(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", tmp_path)
    tid = "top-crop-tee-v1"
    path = f"/v1/catalog/garments/{tid}/preview"
    assert client.get(path).status_code == 404
    (tmp_path / (tid + ".webp")).write_bytes(b"RIFF1234WEBPtest")
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.content == b"RIFF1234WEBPtest"
    items = client.get("/v1/catalog/garments?category=top").json()["categories"][0]["garments"]
    shown = next(x for x in items if x["id"] == tid)
    assert shown["previewStatus"] == "ready"
    assert shown["previewUrl"] == path
    assert client.get("/v1/catalog/garments/not-a-template/preview").status_code == 404


def test_public_preview_cannot_serve_restricted_categories(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", tmp_path)
    # Even a physically present preview is hidden if the viewer lacks an admin session.
    tid = "under-bralette-v1"
    (tmp_path / (tid + ".webp")).write_bytes(b"RIFF1234WEBPtest")
    assert client.get(f"/v1/catalog/garments/{tid}/preview").status_code == 404


def test_customize_validates_template_and_queues_real_job(client, orchestrator, monkeypatch):
    submit = AsyncMock(return_value=SimpleNamespace(id="job_catalog_demo", state=JobState.QUEUED))
    monkeypatch.setattr(orchestrator, "submit", submit)
    payload = {
        "avatar": {"storageKey": "sources/current-avatar.vrm", "avatarId": "demo"},
        "prompt": "Replace the top with a cropped tee",
        "templateId": "top-crop-tee-v1",
        "color": "red",
        "options": {"renderPreview": True, "engine": "native"},
    }
    assert client.post("/v1/catalog/customize", json={**payload, "templateId": "missing"}).status_code == 422
    response = client.post("/v1/catalog/customize", json=payload)
    assert response.status_code == 202
    assert response.json()["jobId"] == "job_catalog_demo"
    job = submit.call_args.args[0]
    assert job.outfit.template_id == payload["templateId"]
    assert job.outfit.color == "red"
    assert job.options.private is False
