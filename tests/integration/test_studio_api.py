"""The Studio over HTTP: served, stocked, dressing, exporting."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from apps.api import main as main_module
from apps.api.main import app
from tests.library_support import write_library
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline import orchestrator as orchestrator_module
from wardrobe.pipeline.plan_outfit import COLORS, HEM_KEYWORDS, SILHOUETTE_KEYWORDS


def make_client(orchestrator, monkeypatch, library: AvatarLibrary) -> TestClient:
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    # The lifespan loads the library from settings; hand it this one instead.
    monkeypatch.setattr(main_module.AvatarLibrary, "from_directory", classmethod(lambda cls, root: library))
    return TestClient(app)


@pytest.fixture
def library(tmp_path, vrm_bytes) -> AvatarLibrary:
    return AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))


@pytest.fixture
def client(orchestrator, monkeypatch, library):
    with make_client(orchestrator, monkeypatch, library) as test_client:
        yield test_client


def wait_for(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    loop_until = timeout / 0.1
    for _ in range(int(loop_until)):
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["state"] in ("completed", "failed", "rejected"):
            return job
        asyncio.run(asyncio.sleep(0.1))
    raise AssertionError(f"job {job_id} did not finish: {job['state']}")


def dress(client: TestClient, slug: str = "mira", base_look_id: str | None = None, **outfit) -> dict:
    body = {
        "outfit": {"prompt": "black pencil skirt", "mode": "template", **outfit},
        "options": {"renderPreview": False, "engine": "native"},
    }
    if base_look_id:
        body["baseLookId"] = base_look_id
    response = client.post(f"/v1/library/{slug}/jobs", json=body)
    assert response.status_code == 202, response.text
    return wait_for(client, response.json()["id"])


# ----------------------------------------------------------------------
# served
# ----------------------------------------------------------------------
def test_the_root_opens_the_studio(client: TestClient):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/studio/"


def test_the_studio_is_served_with_its_pinned_renderer(client: TestClient):
    page = client.get("/studio/").text
    importmap = json.loads(page.split('<script type="importmap">')[1].split("</script>")[0])
    # Pinned to what yourfriend.online ships, so a look that renders here renders there.
    assert "three@0.179.1" in importmap["imports"]["three"]
    assert "three-vrm@3.4.4" in importmap["imports"]["@pixiv/three-vrm"]
    for asset in ("studio.css", "js/app.js", "js/api.js", "js/viewer.js"):
        assert client.get(f"/studio/{asset}").status_code == 200


# ----------------------------------------------------------------------
# library
# ----------------------------------------------------------------------
def test_library_lists_avatars_with_provenance(client: TestClient, library: AvatarLibrary):
    (avatar,) = client.get("/v1/library").json()["avatars"]
    assert avatar["slug"] == "mira"
    assert avatar["available"] is True
    assert avatar["storageKey"] == library.avatars[0].storage_key
    assert avatar["licenseGrants"] == {"modification": "allow", "redistribution": "allow"}


def test_library_serves_the_pinned_bytes(client: TestClient, vrm_bytes: bytes, library: AvatarLibrary):
    response = client.get("/v1/library/mira/avatar.vrm")
    assert response.status_code == 200
    assert response.content == vrm_bytes
    assert response.headers["etag"] == f'"{library.avatars[0].sha256}"'
    assert client.get("/v1/library/nobody/avatar.vrm").status_code == 404


# ----------------------------------------------------------------------
# vocabulary
# ----------------------------------------------------------------------
def test_vocabulary_offers_only_what_the_planner_reads(client: TestClient):
    vocabulary = client.get("/v1/vocabulary").json()
    overrides = vocabulary["overrides"]
    assert {color["name"] for color in overrides["color"]} <= set(COLORS)
    assert set(overrides["silhouette"]) == set(SILHOUETTE_KEYWORDS)
    assert set(overrides["hem"]) == set(HEM_KEYWORDS)
    assert "completed" not in vocabulary["jobStates"]
    assert set(vocabulary["terminalStates"]) == {"completed", "failed", "rejected"}


# ----------------------------------------------------------------------
# dressing a library avatar
# ----------------------------------------------------------------------
def test_a_library_job_completes_under_strict_licensing_and_lands_in_the_slug_wardrobe(client: TestClient):
    job = dress(client, category="skirt", color="black")
    assert job["state"] == "completed", job.get("error")
    assert job["request"]["avatar"]["license"]["source"] == "library:mira"
    wardrobe = client.get("/v1/wardrobes/mira").json()
    assert job["look"]["id"] in [look["id"] for look in wardrobe["looks"]]


def test_the_request_body_cannot_choose_the_avatar_or_its_licence(client: TestClient, library: AvatarLibrary):
    response = client.post(
        "/v1/library/mira/jobs",
        json={
            "avatar": {
                "storageKey": "sources/elsewhere.vrm",
                "license": {"userAttestsModificationAllowed": True},
            },
            "outfit": {"prompt": "black pencil skirt", "mode": "template"},
            "options": {"renderPreview": False, "engine": "native", "wardrobeId": "someone-else"},
        },
    )
    assert response.status_code == 202
    request = response.json()["request"]
    assert request["avatar"]["storageKey"] == library.avatars[0].storage_key
    assert request["avatar"]["license"]["userAttestsModificationAllowed"] is False
    assert request["options"]["wardrobeId"] == "mira"


def test_an_unknown_library_avatar_is_a_404(client: TestClient):
    response = client.post("/v1/library/nobody/jobs", json={"outfit": {"prompt": "red dress"}})
    assert response.status_code == 404


def test_without_a_licence_grant_nothing_is_claimed_and_the_model_decides(
    orchestrator, monkeypatch, tmp_path, vrm_bytes
):
    """A licence the library does not map attests nothing; the avatar's own terms carry the job.

    The calibration avatar embeds `allowed_with_redistribution`, so it completes on
    that alone — which is the point: no condition was supplied on its behalf.
    """
    unmapped = AvatarLibrary.from_directory(
        write_library(tmp_path / "unmapped", {"Mira.vrm": vrm_bytes}, license="personal use only")
    )
    with make_client(orchestrator, monkeypatch, unmapped) as client:
        job = dress(client)
    assert job["state"] == "completed", job.get("error")
    license = job["request"]["avatar"]["license"]
    assert license["conditionsOfUse"] == {}
    assert license["userAttestsModificationAllowed"] is False


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------
def test_export_is_a_bundle_the_chatbot_can_unzip(client: TestClient):
    job = dress(client, category="skirt", color="black")
    response = client.get("/v1/wardrobes/mira/bundle.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-wardrobe-looks"] == "1"

    bundle = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(bundle.read("wardrobe.json"))
    (look,) = [item for item in manifest["looks"] if item["vrmUrl"]]
    assert look["id"] == job["look"]["id"]
    assert bundle.read(look["vrmUrl"])[:4] == b"glTF"


def test_export_of_an_unknown_wardrobe_is_a_404(client: TestClient):
    assert client.get("/v1/wardrobes/nobody/bundle.zip").status_code == 404


def test_passed_only_with_nothing_passing_is_a_409_with_the_reason(client: TestClient, orchestrator):
    dress(client, category="skirt", color="black")
    manifest = asyncio.run(orchestrator.wardrobes.get("mira"))
    for look in manifest.looks:
        if look.type != "source":
            look.fit_passed = False
    asyncio.run(orchestrator.wardrobes.save(manifest))

    response = client.get("/v1/wardrobes/mira/bundle.zip?passedOnly=true")
    assert response.status_code == 409
    assert "fit" in response.json()["detail"]


# ----------------------------------------------------------------------
# try-on haul
# ----------------------------------------------------------------------
def test_vocabulary_names_the_categories_that_need_an_adult_declaration(client: TestClient):
    vocabulary = client.get("/v1/vocabulary").json()
    assert vocabulary["intimateCategories"] == ["swimwear", "underwear"]
    assert {"swimwear", "underwear", "nightwear", "shorts", "legwear"} <= set(vocabulary["overrides"]["category"])


def test_an_undeclared_library_avatar_cannot_be_put_in_swimwear(client: TestClient):
    job = dress(client, prompt="red triangle bikini")
    assert job["state"] == "rejected"
    assert job["reason"] == "requires_adult_declaration"


def test_a_declared_library_avatar_can_and_the_body_cannot_declare_it(orchestrator, monkeypatch, tmp_path, vrm_bytes):
    # Both built before make_client, which patches AvatarLibrary.from_directory on the class.
    root = write_library(tmp_path / "declared", {"Mira.vrm": vrm_bytes})
    (root / "policy.json").write_text(json.dumps({"avatars": {"mira": {"depictsAdult": True}}}))
    declared = AvatarLibrary.from_directory(root)
    undeclared = AvatarLibrary.from_directory(write_library(tmp_path / "plain", {"Mira.vrm": vrm_bytes}))
    assert declared.get("mira").depicts_adult and not undeclared.get("mira").depicts_adult

    with make_client(orchestrator, monkeypatch, declared) as client:
        assert client.get("/v1/library").json()["avatars"][0]["depictsAdult"] is True
        assert dress(client, prompt="red triangle bikini")["state"] == "completed"

    with make_client(orchestrator, monkeypatch, undeclared) as client:
        response = client.post(
            "/v1/library/mira/jobs",
            json={"avatar": {"depictsAdult": True}, "outfit": {"prompt": "red triangle bikini"}},
        )
        # What the server wrote into the job is the whole point; that the gate then
        # refuses an undeclared avatar is test_an_undeclared_library_avatar_cannot_be_put_in_swimwear.
        assert response.json()["request"]["avatar"]["depictsAdult"] is False


# ----------------------------------------------------------------------
# outfit sets: building on a look already in the wardrobe
# ----------------------------------------------------------------------
def test_a_set_is_built_on_a_previous_look_and_a_second_top_replaces_the_first(client: TestClient, orchestrator):
    from tests.vroid_support import primitive_materials

    top = dress(client, prompt="white crop top")
    assert top["state"] == "completed", top.get("error")
    skirt = dress(client, prompt="navy pleated mini skirt", base_look_id=top["look"]["id"])
    assert skirt["state"] == "completed", skirt.get("error")
    assert skirt["request"]["avatar"]["storageKey"] == f"looks/{top['look']['id']}/look.vrm"

    swap = dress(client, prompt="black tube top", base_look_id=skirt["look"]["id"])
    worn = primitive_materials(asyncio.run(orchestrator.store.get(f"looks/{swap['look']['id']}/look.vrm")))
    tops = [name for name in worn if "[Forge_Tops_" in name]
    assert len(tops) == 1 and tops[0].startswith(swap["plan"]["name"])
    assert any("[Forge_Bottoms_" in name for name in worn)  # the skirt stays


def test_a_set_cannot_be_built_on_another_avatars_look(orchestrator, monkeypatch, tmp_path, vrm_bytes):
    library = AvatarLibrary.from_directory(write_library(tmp_path / "two", {"Mira.vrm": vrm_bytes, "Nia.vrm": vrm_bytes}))
    with make_client(orchestrator, monkeypatch, library) as client:
        mira = dress(client, "mira", prompt="white crop top")
        body = {"outfit": {"prompt": "navy skirt", "mode": "template"}, "baseLookId": mira["look"]["id"]}
        assert client.post("/v1/library/nia/jobs", json=body).status_code == 404
        body["baseLookId"] = "look_does_not_exist"
        assert client.post("/v1/library/mira/jobs", json=body).status_code == 404
