"""PB2. Over HTTP: a library look made once is answered at once and listed as ready for her."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.test_studio_api import client, dress, library  # noqa: F401  (fixtures)

TEE = "top-fitted-tee-v1"


def test_the_second_request_is_answered_on_its_first_poll(client: TestClient):  # noqa: F811
    first = dress(client, templateId=TEE, prompt="fitted tee")
    assert first["state"] == "completed", first.get("error")

    body = {"outfit": {"prompt": "the tee again", "mode": "template", "templateId": TEE},
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
