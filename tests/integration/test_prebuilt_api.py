"""PB2. Over HTTP: a library look made once is answered at once and listed as ready for her."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.test_studio_api import client, dress, library  # noqa: F401  (fixtures)

TEE = "top-fitted-tee-v1"


def test_the_second_request_is_answered_on_its_first_poll(client: TestClient):  # noqa: F811
    first = dress(client, templateId=TEE, prompt="fitted tee")
    assert first["state"] == "completed", first.get("error")

    body = {"outfit": {"prompt": "fitted tee", "mode": "template", "templateId": TEE},
            "options": {"renderPreview": False, "engine": "native"}}
    accepted = client.post("/v1/library/mira/jobs", json=body)
    assert accepted.status_code == 202, accepted.text
    again = client.get(f"/v1/jobs/{accepted.json()['id']}").json()
    assert again["state"] == "completed"  # no waiting: read straight back
    assert again["look"]["id"] == first["look"]["id"]
    assert again["events"][-1]["detail"]["cache"] == "prebuilt"


def test_ready_looks_are_listed_for_her_and_a_look_on_a_look_is_not(client: TestClient):  # noqa: F811
    assert client.get("/v1/library/mira/prebuilt").json()["looks"] == []
    tee = dress(client, templateId=TEE, prompt="fitted tee")
    dress(client, templateId="skirt-pencil-v1", prompt="pencil skirt", base_look_id=tee["look"]["id"])

    listed = client.get("/v1/library/mira/prebuilt").json()
    assert listed["count"] == 1
    item = listed["looks"][0]
    assert item["templateId"] == TEE and item["lookId"] == tee["look"]["id"]
    assert item["vrmUrl"] and item["private"] is False
    assert client.get("/v1/library/nobody/prebuilt").status_code == 404


def test_her_wardrobe_lists_prebuilt_looks_after_a_restart(client: TestClient, orchestrator):  # noqa: F811
    import asyncio

    from wardrobe.storage.database import InMemoryWardrobeRepository

    tee = dress(client, templateId=TEE, prompt="fitted tee")
    orchestrator.wardrobes = InMemoryWardrobeRepository()  # what a restarted Space remembers: nothing
    assert asyncio.run(orchestrator.wardrobes.get("mira")) is None

    wardrobe = client.get("/v1/wardrobes/mira").json()
    assert tee["look"]["id"] in [look["id"] for look in wardrobe["looks"]]
    assert client.get("/v1/wardrobes/nobody").status_code == 404


def test_known_avatar_without_prebuilts_has_an_empty_wardrobe(client: TestClient):  # noqa: F811
    response = client.get("/v1/wardrobes/mira")
    assert response.status_code == 200, response.text
    assert response.json()["avatarId"] == "mira"
    assert [look["type"] for look in response.json()["looks"]] == ["source"]
    assert client.get("/v1/wardrobes/mira/avatars.json").json()["items"] == []
    assert client.get("/v1/wardrobes/nobody").status_code == 404


def test_prebuilt_exposure_and_layering_survive_restart(client: TestClient, orchestrator):  # noqa: F811
    from wardrobe.storage.database import InMemoryWardrobeRepository

    tee = dress(client, templateId=TEE, prompt="fitted tee")
    look_id = tee["look"]["id"]
    orchestrator.wardrobes = InMemoryWardrobeRepository()

    exposure = client.get(f"/v1/library/mira/looks/{look_id}/exposure")
    assert exposure.status_code == 200, exposure.text
    assert exposure.json()["lookId"] == look_id
    assert "placements" in exposure.json()
    layered = dress(client, templateId="skirt-pencil-v1", prompt="pencil skirt",
                    base_look_id=look_id)
    assert layered["state"] == "completed", layered.get("error")


def test_missing_prebuilt_preview_is_not_advertised(client: TestClient, orchestrator):  # noqa: F811
    import asyncio
    import json

    from wardrobe.pipeline import prebuilt
    from wardrobe.storage.database import InMemoryWardrobeRepository

    tee = dress(client, templateId=TEE, prompt="fitted tee")
    look_id = tee["look"]["id"]
    key = prebuilt.wardrobe_key("mira")
    listed = json.loads(asyncio.run(orchestrator.store.get(key)))
    listed["looks"][0]["previewUrl"] = f"/v1/assets/looks/{look_id}/preview.webp"
    asyncio.run(orchestrator.store.put(key, json.dumps(listed).encode()))
    orchestrator.wardrobes = InMemoryWardrobeRepository()

    ready = client.get("/v1/library/mira/prebuilt")
    assert ready.status_code == 200
    assert ready.json()["looks"][0]["previewUrl"] is None
    manifest = client.get("/v1/wardrobes/mira").json()
    assert next(look for look in manifest["looks"] if look["id"] == look_id)["previewUrl"] is None


def test_private_prebuilt_remains_hidden_after_restart(client: TestClient, orchestrator):  # noqa: F811
    import asyncio
    import json

    from wardrobe.pipeline import prebuilt
    from wardrobe.storage.database import InMemoryWardrobeRepository

    tee = dress(client, templateId=TEE, prompt="fitted tee")
    look_id = tee["look"]["id"]
    key = prebuilt.wardrobe_key("mira")
    listed = json.loads(asyncio.run(orchestrator.store.get(key)))
    listed["looks"][0]["private"] = True
    asyncio.run(orchestrator.store.put(key, json.dumps(listed).encode()))
    orchestrator.wardrobes = InMemoryWardrobeRepository()

    assert client.get("/v1/library/mira/prebuilt").json()["count"] == 0
    assert client.get(f"/v1/library/mira/looks/{look_id}/exposure").status_code == 404
    assert [look["type"] for look in client.get("/v1/wardrobes/mira").json()["looks"]] == ["source"]


def test_missing_preview_in_legacy_local_manifest_is_suppressed(client: TestClient, orchestrator):  # noqa: F811
    import asyncio

    from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest

    broken = WardrobeManifest.empty("mira")
    broken.upsert(WardrobeLook(
        id="look_stale", name="Older look", vrmUrl="/v1/assets/looks/look_stale/look.vrm",
        previewUrl="/v1/assets/looks/look_stale/preview.webp",
    ))
    asyncio.run(orchestrator.wardrobes.save(broken))
    returned = client.get("/v1/wardrobes/mira")
    assert returned.status_code == 200
    legacy = next(item for item in returned.json()["looks"] if item["id"] == "look_stale")
    assert legacy["previewUrl"] is None
