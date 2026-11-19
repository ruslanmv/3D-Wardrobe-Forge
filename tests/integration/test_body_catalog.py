"""BD21. What a client needs to tell her what her bare looks can show: the catalogue, read with a
grant, and each bare look's own ``body`` (preset, states, extras) in her wardrobe listing."""

from __future__ import annotations

import asyncio
import json

from tests.integration.test_registry_api import env  # noqa: F401  (fixture)
from wardrobe.domain.jobs import JobOptions
from wardrobe.pipeline import prebuilt
from wardrobe.vrm import body_detail


def test_the_catalogue_is_private_and_names_every_state_and_extra(env):  # noqa: F811
    client, admin, grant, _ = env
    assert client.get("/v1/body-surface/catalog").status_code == 403
    assert (
        client.get("/v1/body-surface/catalog", headers={"X-Wardrobe-Grant": "forged.token"}).status_code
        == 403
    )
    for headers in (admin, grant):
        res = client.get("/v1/body-surface/catalog", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert set(data["states"]) == set(body_detail.load_states())
        assert set(data["extras"]) == set(body_detail.load_extras())
        assert set(data["presets"]) == set(body_detail.load_presets())
        # Every state and extra comes with the line the conversation needs, not only a name.
        assert all(s["body"] and s["label"] for s in data["states"].values())
        assert all(e["body"] and e["kind"] for e in data["extras"].values())
        assert data["extras"]["piercings-labia"]["kind"] == "piercings"
        assert data["extras"]["tattoo-mons-rose"]["kind"] == "tattoo"


def test_a_bare_job_says_what_its_body_is_and_a_dressed_one_says_nothing():
    bare = JobOptions.model_validate(
        {
            "baseBody": "bare",
            "bareDetail": "natural",
            "bareStates": ["closed", "aroused", "aroused"],
            "bareExtras": ["piercings-nipples"],
        }
    )
    assert bare.body_summary() == {
        "detail": "natural",
        "state": "closed",
        "states": ["closed", "aroused"],
        "extras": ["piercings-nipples"],
        "skinPack": True,
    }
    assert JobOptions.model_validate({"baseBody": "bare"}).body_summary() is None
    assert JobOptions().body_summary() is None


def test_her_wardrobe_lists_a_bare_looks_body_to_a_grant_only(env, orchestrator):  # noqa: F811
    client, admin, grant, _ = env
    body = {
        "detail": "natural",
        "state": "closed",
        "states": ["closed", "open"],
        "extras": [],
        "skinPack": True,
    }
    item = {
        "key": "k",
        "templateId": "body-bare-v1",
        "lookId": "look_bare1",
        "name": "Bare · natural",
        "vrmUrl": "https://x/v1/assets/looks/look_bare1/avatar.vrm",
        "private": True,
        "body": body,
        "wardrobeState": "bare",
    }
    asyncio.run(orchestrator.store.put(prebuilt.wardrobe_key("mira"), json.dumps({"looks": [item]}).encode()))
    guest = client.get("/v1/wardrobes/mira").json()["looks"]
    assert all(look.get("id") != "look_bare1" for look in guest)
    for headers in (admin, grant):
        looks = client.get("/v1/wardrobes/mira", headers=headers).json()["looks"]
        bare = next(look for look in looks if look["id"] == "look_bare1")
        assert bare["body"] == body


def _bare_record(look_id: str, **options):
    from types import SimpleNamespace

    from wardrobe.domain.jobs import CreateJobRequest

    request = CreateJobRequest.model_validate(
        {
            "avatar": {"avatarId": "mira", "storageKey": "sources/mira.vrm", "depictsAdult": True},
            "outfit": {"prompt": "Bare authored body", "mode": "template", "templateId": "body-bare-v1"},
            "options": {"baseBody": "bare", "private": True, "wardrobeId": "mira", **options},
        }
    )
    look = SimpleNamespace(
        id=look_id,
        name="Bare",
        vrm_url=f"https://x/{look_id}.vrm",
        preview_url=None,
        prompt=None,
        wardrobe_state="bare",
        source_avatar_hash="a" * 64,
        output_sha256="b" * 64,
    )
    return SimpleNamespace(request=request, look=look, fit_report=None, plan=None)


def test_every_detailed_bare_look_is_listed_and_a_plain_one_is_kept(orchestrator):
    store = orchestrator.store
    plain = _bare_record("look_plain")
    pumped = _bare_record("look_pumped", bareDetail="natural", bareStates=["closed", "pumped"])
    pierced = _bare_record("look_pierced", bareDetail="trimmed", bareExtras=["piercings-all"])
    for i, record in enumerate((plain, pumped, pierced)):
        asyncio.run(prebuilt._list_look(store, record, f"key{i}"))
    # The same plain bare look again never replaces the one already listed.
    asyncio.run(prebuilt._list_look(store, _bare_record("look_plain_again"), "key9"))
    looks = json.loads(asyncio.run(store.get(prebuilt.wardrobe_key("mira"))))["looks"]
    assert [look["lookId"] for look in looks] == ["look_plain", "look_pumped", "look_pierced"]
    assert "body" not in looks[0]
    assert looks[1]["body"]["states"] == ["closed", "pumped"]
    assert looks[2]["body"]["extras"] == ["piercings-all"]
