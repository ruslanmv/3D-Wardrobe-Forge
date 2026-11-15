"""BI1/BI2 over HTTP: an operator imports a body state; a companion reads it with a grant, not a token.

What must hold:

* only an admin session imports, lists or withdraws; a refusal says every check's answer;
* an accepted import is private, bound to her pinned hash, listed with BL1's identity fields and
  readable after a restart (a new process over the same storage);
* a read grant lists and serves her private looks and nobody else's, never writes, and an
  expired, tampered or revoked grant is nothing; the admin token is never what a consumer needs.

The avatar is the calibration body with a test box on its head (``tests/support_body_state``),
declared for the session exactly as ``test_admin_session`` does: these tests exercise the
mechanism, not a judgement about anyone's avatar.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from tests.conftest import clear_design_for_test
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from tests.support_body_state import edited, move_face, touch, with_head
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.policy import grants
from wardrobe.storage.object_store import LocalObjectStore

PASSWORD = "correct horse battery staple"
SECRET = "s" * 40


def permitting(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def mira(vrm_bytes) -> bytes:
    return with_head(edited(vrm_bytes, permitting))


@pytest.fixture
def state(mira) -> bytes:
    return edited(mira, touch)


@pytest.fixture
def env(orchestrator, monkeypatch, tmp_path, settings, mira, vrm_bytes, template_catalog):
    settings.wardrobe_adult_body_surface = True
    settings.wardrobe_grant_secret = SECRET
    library = AvatarLibrary.from_directory(
        write_library(tmp_path / "library", {"Mira.vrm": mira, "Nora.vrm": with_head(vrm_bytes)}))
    admins = AdminSessions(PASSWORD, ttl_hours=1)
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    app.dependency_overrides[settings_dependency] = lambda: settings

    def client(orch=orchestrator) -> TestClient:
        return make_client(orch, monkeypatch, library)

    try:
        yield {"client": client, "settings": settings, "library": library, "catalog": template_catalog}
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)
        app.dependency_overrides.pop(settings_dependency, None)


def sign_in(client: TestClient, declare: tuple[str, ...] = ("mira", "nora")) -> dict:
    token = client.post("/v1/admin/session", json={"username": "admin", "password": PASSWORD}).json()["token"]
    headers = {"X-Wardrobe-Admin": token}
    for slug in declare:
        response = client.put(f"/v1/admin/declarations/{slug}", headers=headers,
                              json={"depictsAdult": True, "ageConfirmed": True})
        assert response.status_code == 200, response.text
    return headers


def upload(client, headers, data, *, slug="mira", state="bare", source=None, digest=None, attested=True):
    form = {"state": state, "sourceSha256": source or "", "licence": "operator-held test licence",
            "rightsAttested": "true" if attested else "false"}
    if digest is not None:
        form["sha256"] = digest
    return client.post(f"/v1/admin/library/{slug}/body-states", headers=headers, data=form,
                       files={"file": ("state.vrm", data, "model/gltf-binary")})


def grant_for(client, headers, *slugs, ttl=3600) -> dict:
    response = client.post("/v1/admin/grants", headers=headers, json={"slugs": list(slugs), "ttlSeconds": ttl})
    assert response.status_code == 201, response.text
    return {grants.HEADER: response.json()["token"]}


def test_import_is_admin_only_and_needs_attestation(env, mira, state):
    with env["client"]() as client:
        assert upload(client, {}, state, source=sha(mira)).status_code == 401
        headers = sign_in(client)
        response = upload(client, headers, state, source=sha(mira), attested=False)
        assert response.json()["detail"]["reason"] == "rights_not_attested"


def test_refusal_reports_every_check(env, mira, state):
    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        wrong = upload(client, headers, state, source=sha(mira), digest="0" * 64)
        assert wrong.status_code == 422 and wrong.json()["detail"]["reason"] == "body_state_sha256_mismatch"
        moved = upload(client, headers, edited(mira, move_face), source=sha(mira))
        assert moved.json()["detail"]["reason"] == "body_state_identity_mismatch"
        assert moved.json()["detail"]["verdict"]["checks"]["rig"]["passed"] is True
        other = upload(client, headers, state, source="a" * 64)
        assert other.json()["detail"]["reason"] == "body_state_source_mismatch"
        assert client.get("/v1/admin/library/mira/body-states", headers=headers).json()["count"] == 0


def test_bare_without_a_review_of_the_import_is_refused(env, mira, state):
    clear_design_for_test(env["settings"], mira)
    with env["client"]() as client:
        response = upload(client, sign_in(client), state, source=sha(mira))
        assert response.json()["detail"]["reason"] == "body_state_not_permitted"
        assert response.json()["detail"]["verdict"]["checks"]["eligibility-import"]["refusedBy"] == \
            "design-clearance"


def test_accepted_import_is_private_bound_listed_and_survives_a_restart(env, mira, state, settings,
                                                                      template_catalog):
    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        response = upload(client, headers, state, source=sha(mira), digest=sha(state))
        assert response.status_code == 201, response.text
        look = response.json()["look"]
        assert look["wardrobeState"] == "bare" and look["private"] is True
        assert look["sourceSha256"] == sha(mira) and look["outputSha256"] == sha(state)
        assert look["origin"] == "operator-import"
        url = look["vrmUrl"].split("/v1/", 1)[1]
        # Nobody without a session or a grant sees it, anywhere.
        assert all(item["id"] != look["lookId"] for item in client.get("/v1/wardrobes/mira").json()["looks"])
        assert client.get("/v1/library/mira/prebuilt").json()["count"] == 0
        assert client.get(f"/v1/{url}").status_code == 404
        assert client.get(f"/v1/{url}", headers=headers).content == state
        # Re-uploading the same bytes is the same look, not a second one.
        assert upload(client, headers, state, source=sha(mira)).status_code == 201
        assert client.get("/v1/admin/library/mira/body-states", headers=headers).json()["count"] == 1
        token = grant_for(client, headers, "mira")

    # A new process over the same storage: new orchestrator, new admin sessions, nothing in memory.
    fresh = Orchestrator(settings=settings, store=LocalObjectStore(settings.wardrobe_storage_root, settings),
                         catalog=template_catalog)
    app.dependency_overrides[admin_sessions_dependency] = lambda: AdminSessions(PASSWORD, ttl_hours=1)
    with env["client"](fresh) as client:
        wardrobe = client.get("/v1/wardrobes/mira", headers=token).json()
        found = [item for item in wardrobe["looks"] if item["id"] == look["lookId"]]
        assert found and found[0]["wardrobeState"] == "bare" and found[0]["outputSha256"] == sha(state)
        assert found[0]["origin"] == "operator-import"
        served = client.get(f"/v1/{url}", headers=token)
        assert served.status_code == 200 and sha(served.content) == sha(state)
        assert client.get("/v1/library/mira/prebuilt", headers=token).json()["count"] == 1


def test_a_grant_reads_only_its_avatars_and_writes_nothing(env, mira, state):
    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        url = upload(client, headers, state, source=sha(mira)).json()["look"]["vrmUrl"].split("/v1/", 1)[1]
        nora = grant_for(client, headers, "nora")
        assert client.get(f"/v1/{url}", headers=nora).status_code == 404
        assert client.get("/v1/library/mira/prebuilt", headers=nora).json()["count"] == 0
        mine = grant_for(client, headers, "mira")
        # A grant is not a session: every write refuses it.
        assert upload(client, mine, state, source=sha(mira)).status_code == 401
        assert client.post("/v1/admin/grants", headers=mine, json={"slugs": ["mira"]}).status_code == 401
        assert client.put("/v1/admin/declarations/mira", headers=mine,
                          json={"depictsAdult": True, "ageConfirmed": True}).status_code == 401
        look_id = url.split("/")[2]
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=mine).status_code == 401
        # Tampered and revoked grants are nothing.
        tampered = {grants.HEADER: mine[grants.HEADER][:-2] + "xx"}
        assert client.get(f"/v1/{url}", headers=tampered).status_code == 404
        env["settings"].wardrobe_grant_revoked = grants.verify(SECRET, mine[grants.HEADER]).id
        assert client.get(f"/v1/{url}", headers=mine).status_code == 404
        env["settings"].wardrobe_grant_revoked = ""
        assert client.get(f"/v1/{url}", headers=mine).status_code == 200
        # Withdrawn: gone from her list and from storage.
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 204
        assert client.get(f"/v1/{url}", headers=headers).status_code == 404
        assert client.get("/v1/library/mira/prebuilt", headers=mine).json()["count"] == 0


def test_no_secret_no_grants(env):
    env["settings"].wardrobe_grant_secret = "short"
    with env["client"]() as client:
        response = client.post("/v1/admin/grants", headers=sign_in(client), json={"slugs": ["mira"]})
        assert response.status_code == 409 and response.json()["detail"]["reason"] == "grants_unavailable"


def test_grant_tokens_expire_and_are_bounded():
    token, grant = grants.mint(SECRET, slugs=["mira"], ttl_s=60, now=1000)
    assert grants.verify(SECRET, token, now=1059).covers("mira")
    assert grants.verify(SECRET, token, now=1060) is None
    assert grants.verify("t" * 40, token, now=1000) is None
    with pytest.raises(grants.GrantError):
        grants.mint(SECRET, slugs=["mira"], ttl_s=grants.MAX_TTL_S + 1)
    with pytest.raises(grants.GrantError):
        grants.mint(SECRET, slugs=["../etc"], ttl_s=60)


def test_garments_come_from_the_file_or_a_checked_operator_list(env, mira, state):
    """The generated body has no Forge garment tags: unknown unless the operator names catalogue
    templates, and a name the catalogue does not have is refused."""
    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        form = {"state": "lingerie", "sourceSha256": sha(mira), "licence": "operator-held test licence",
                "rightsAttested": "true"}
        files = {"file": ("state.vrm", state, "model/gltf-binary")}
        bad = client.post("/v1/admin/library/mira/body-states", headers=headers,
                          data={**form, "garments": "not-a-template"}, files=files)
        assert bad.json()["detail"]["reason"] == "body_state_garments_unknown"
        ok = client.post("/v1/admin/library/mira/body-states", headers=headers,
                         data={**form, "garments": "under-chemise-satin-v1"}, files=files)
        look = ok.json()["look"]
        assert look["garments"] == ["under-chemise-satin-v1"] and look["templateId"] == "under-chemise-satin-v1"
        listed = client.get("/v1/wardrobes/mira", headers=headers).json()["looks"]
        mine = next(item for item in listed if item["id"] == look["lookId"])
        assert mine["garments"] == ["under-chemise-satin-v1"] and mine["templateId"] == "under-chemise-satin-v1"


def test_a_failed_vrm_deletion_keeps_the_marker_and_a_retry_finishes(env, mira, state, monkeypatch):
    """BI1 (review finding): the marker used to be deleted even when look.vrm could not be, and the
    VRM then served to anyone. Now it stays private until it is gone, and DELETE can be repeated."""
    from wardrobe.storage.object_store import LocalObjectStore

    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        url = upload(client, headers, state, source=sha(mira)).json()["look"]["vrmUrl"].split("/v1/", 1)[1]
        look_id = url.split("/")[2]
        real_delete = LocalObjectStore.delete

        async def failing(self, key):
            if key.endswith("/look.vrm"):
                raise OSError("disk says no")
            return await real_delete(self, key)

        monkeypatch.setattr(LocalObjectStore, "delete", failing)
        first = client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers)
        assert first.status_code == 503
        assert first.json()["detail"]["remaining"] == [f"looks/{look_id}/look.vrm"]
        assert client.get(f"/v1/{url}").status_code == 404  # still private, anonymously
        assert client.get(f"/v1/{url}", headers=headers).status_code == 200
        assert client.get("/v1/admin/library/mira/body-states", headers=headers).json()["count"] == 0
        # Under another avatar it is not there to withdraw.
        assert client.delete(f"/v1/admin/library/nora/body-states/{look_id}", headers=headers).status_code == 404
        monkeypatch.setattr(LocalObjectStore, "delete", real_delete)
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 204
        assert client.get(f"/v1/{url}", headers=headers).status_code == 404
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=headers).status_code == 404


def test_grants_expire_by_the_clock_and_never_cross_avatars(env, mira, state, monkeypatch):
    clear_design_for_test(env["settings"], mira, state)
    with env["client"]() as client:
        headers = sign_in(client)
        url = upload(client, headers, state, source=sha(mira)).json()["look"]["vrmUrl"].split("/v1/", 1)[1]
        token = grant_for(client, headers, "mira", ttl=60)
        assert client.get(f"/v1/{url}", headers=token).status_code == 200
        assert client.get("/v1/library/nora/prebuilt", headers=token).json()["count"] == 0
        import time as clock

        later = clock.time() + 61
        monkeypatch.setattr(grants.time, "time", lambda: later)
        assert client.get(f"/v1/{url}", headers=token).status_code == 404
        assert client.get(f"/v1/{url}", headers={grants.HEADER: "not.a-grant"}).status_code == 404
