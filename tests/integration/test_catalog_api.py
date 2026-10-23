"""Public garment catalog, cached thumbnails, and customize facade."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import catalog as catalog_routes
from wardrobe.domain.jobs import JobState
from wardrobe.pipeline import orchestrator as orchestrator_module


@pytest.fixture
def client(orchestrator, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    with TestClient(app) as test_client:
        yield test_client


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
    assert shown["previewUrl"].startswith(path + "?v=")
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


def test_preview_url_names_its_bytes_and_only_that_url_is_cached_for_good(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", tmp_path)
    tid = "top-crop-tee-v1"
    file = tmp_path / (tid + ".webp")

    def advertised() -> str:
        items = client.get("/v1/catalog/garments?category=top").json()["categories"][0]["garments"]
        return next(x for x in items if x["id"] == tid)["previewUrl"]

    file.write_bytes(b"RIFF1234WEBPfirst")
    first = advertised()
    assert "immutable" in client.get(first).headers["cache-control"]
    # Unversioned and outdated links still work, but are not cached as if they could never change.
    assert "immutable" not in client.get(f"/v1/catalog/garments/{tid}/preview").headers["cache-control"]

    file.write_bytes(b"RIFF1234WEBPsecond render")
    second = advertised()
    assert second != first  # a re-render is a new URL, so no client keeps the old picture
    assert "immutable" not in client.get(first).headers["cache-control"]
    assert client.get(second).content == b"RIFF1234WEBPsecond render"


def test_counts_cover_only_what_the_viewer_may_see(client, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", tmp_path)
    (tmp_path / "top-crop-tee-v1.webp").write_bytes(b"RIFF1234WEBPtest")
    (tmp_path / "under-bralette-v1.webp").write_bytes(b"RIFF1234WEBPtest")  # restricted
    data = client.get("/v1/catalog/garments").json()
    assert data["previewCount"] == 1
    assert data["visibleCount"] < data["totalTemplates"]
    shown = {item["id"] for group in data["categories"] for item in group["garments"]}
    assert "top-crop-tee-v1" in shown and "under-bralette-v1" not in shown


@pytest.mark.parametrize("payload", [
    # Neither, or both, ways of naming the avatar.
    {"prompt": "a red tee"},
    {"prompt": "a red tee", "librarySlug": "mira", "avatar": {"storageKey": "sources/x.vrm"}},
    # A base look is found in a library avatar's wardrobe, so it needs one.
    {"prompt": "a red tee", "avatar": {"storageKey": "sources/x.vrm"}, "baseLookId": "look_1"},
])
def test_customize_names_the_avatar_exactly_once(client, payload):
    assert client.post("/v1/catalog/customize", json=payload).status_code == 422


def test_customize_on_a_library_look_changes_one_garment_and_keeps_the_rest(orchestrator, monkeypatch, tmp_path,
                                                                            vrm_bytes):
    from tests.integration.test_studio_api import dress, make_client, wait_for
    from tests.library_support import write_library
    from tests.vroid_support import primitive_materials
    from wardrobe.library import AvatarLibrary

    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))
    with make_client(orchestrator, monkeypatch, library) as client:
        skirt = dress(client, prompt="navy pleated mini skirt")
        assert skirt["state"] == "completed", skirt.get("error")
        response = client.post("/v1/catalog/customize", json={
            "librarySlug": "mira", "baseLookId": skirt["look"]["id"],
            "prompt": "red cropped tee", "templateId": "top-crop-tee-v1", "color": "red",
            "options": {"renderPreview": False, "engine": "native"},
        })
        assert response.status_code == 202, response.text
        assert response.json()["statusUrl"] == f"/v1/jobs/{response.json()['jobId']}"
        job = wait_for(client, response.json()["jobId"])
        assert job["state"] == "completed", job.get("error")
        # Built from the look she had on, in her own wardrobe, by the library route's rules.
        assert job["request"]["avatar"]["storageKey"] == f"looks/{skirt['look']['id']}/look.vrm"
        assert job["request"]["options"]["wardrobeId"] == "mira"
        worn = primitive_materials(asyncio.run(orchestrator.store.get(f"looks/{job['look']['id']}/look.vrm")))
        assert any("[Forge_Tops_" in name for name in worn)
        assert any("[Forge_Bottoms_" in name for name in worn)  # the skirt stays

        # Another avatar's look, or one that does not exist, is not hers to build on.
        missing = {"librarySlug": "mira", "baseLookId": "look_does_not_exist", "prompt": "red tee"}
        assert client.post("/v1/catalog/customize", json=missing).status_code == 404
        assert client.post("/v1/catalog/customize", json={"librarySlug": "nobody", "prompt": "red tee"}
                           ).status_code == 404


# ----------------------------------------------------------------------
# the adult collection: complete, separate, and only for an admin session
# ----------------------------------------------------------------------
@pytest.fixture
def adult_previews(tmp_path, monkeypatch):
    public, adult = tmp_path / "public", tmp_path / "adult"
    public.mkdir()
    adult.mkdir()
    monkeypatch.setattr(catalog_routes, "PREVIEW_ROOT", public)
    monkeypatch.setattr(catalog_routes, "ADULT_PREVIEW_ROOT", adult)
    return public, adult


@pytest.fixture
def as_admin():
    from apps.api.admin import current_admin

    app.dependency_overrides[current_admin] = lambda: SimpleNamespace(username="admin")
    yield
    app.dependency_overrides.pop(current_admin, None)


def test_the_adult_collection_is_listed_and_served_only_to_an_admin(client, adult_previews, as_admin):
    public, adult = adult_previews
    tid = "under-bralette-v1"
    (adult / f"{tid}.webp").write_bytes(b"RIFF1234WEBPadult")
    data = client.get("/v1/catalog/garments?category=underwear&includeRestricted=true").json()
    items = data["categories"][0]["garments"]
    assert len(items) == 28 and all(item["requiresAdult"] for item in items)
    shown = next(item for item in items if item["id"] == tid)
    assert shown["previewStatus"] == "ready"
    response = client.get(shown["previewUrl"])
    assert response.status_code == 200 and response.content == b"RIFF1234WEBPadult"
    # Never a shared cache, whatever the URL says.
    assert response.headers["cache-control"] == "private, no-store"
    # Only what was rendered is ready: no thumbnail is claimed for the other 27.
    assert sum(item["previewStatus"] == "ready" for item in items) == 1
    assert all(item["previewUrl"] is None for item in items if item["id"] != tid)


def test_without_an_admin_the_adult_collection_does_not_exist(client, adult_previews):
    public, adult = adult_previews
    tid = "under-bralette-v1"
    (adult / f"{tid}.webp").write_bytes(b"RIFF1234WEBPadult")
    # A copy that strayed into the public folder is not served from there either.
    (public / f"{tid}.webp").write_bytes(b"RIFF1234WEBPstray")
    assert client.get(f"/v1/catalog/garments/{tid}/preview").status_code == 404
    assert client.get("/v1/catalog/garments?includeRestricted=true").status_code == 403
    listed = client.get("/v1/catalog/garments").json()
    assert all(group["id"] not in {"underwear", "swimwear"} for group in listed["categories"])
    assert client.get("/v1/catalog/garments?category=underwear").json()["categories"] == []


def test_colours_and_materials_come_from_what_forge_supports(client):
    from wardrobe.pipeline.plan_outfit import COLORS

    items = [item for group in client.get("/v1/catalog/garments").json()["categories"]
             for item in group["garments"]]
    for item in items:
        assert item["availableColors"] == (sorted(COLORS) if item["supportsColor"] else [])
        assert set(item["supportedMaterials"]) <= {"pattern", "metallic", "finish", "sheer"}
