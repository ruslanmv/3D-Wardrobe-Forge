"""CG4 over HTTP: the Studio's character review records one person's finding, and nothing else.

What must hold:

* only an admin session lists or records; a guest gets 401;
* a missing review is ``pending`` (work to do), not a rejection; a recorded ``age-ambiguous`` is a
  finding that blocks those bytes;
* nothing is recorded without the person's own outcome, name, evidence and "I looked" tick, and a
  hash other than the file's pin is refused;
* a finding is written once for those bytes, to a temporary copy of the registry, never the
  committed one; after a ``clearly-adult`` finding the character's status moves on to its body.

The avatars are the calibration body with a test head (``tests/support_body_state``): these tests
exercise the mechanism and record test findings about generated fixtures, not about any character.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from tests.support_body_state import edited, with_head
from wardrobe.library import AvatarLibrary

PASSWORD = "correct horse battery staple"


def permitting(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


@pytest.fixture
def mira(vrm_bytes) -> bytes:
    return with_head(edited(vrm_bytes, permitting))


@pytest.fixture
def env(orchestrator, monkeypatch, tmp_path, settings, mira):
    root = tmp_path / "body_surface"
    shutil.copytree(settings.body_surface_root_path, root)
    settings.wardrobe_body_surface_root = str(root)
    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": mira}))
    admins = AdminSessions(PASSWORD, ttl_hours=1)
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    app.dependency_overrides[settings_dependency] = lambda: settings
    try:
        yield {"client": lambda: make_client(orchestrator, monkeypatch, library),
               "registry": root / "adult-design-reviews.json", "sha": hashlib.sha256(mira).hexdigest(),
               "monkeypatch": monkeypatch}
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)
        app.dependency_overrides.pop(settings_dependency, None)


def sign_in(client: TestClient) -> dict:
    token = client.post("/v1/admin/session", json={"username": "admin", "password": PASSWORD}).json()["token"]
    headers = {"X-Wardrobe-Admin": token}
    response = client.put("/v1/admin/declarations/mira", headers=headers,
                          json={"depictsAdult": True, "ageConfirmed": True})
    assert response.status_code == 200, response.text
    return headers


def finding(sha: str, **change) -> dict:
    return {"sha256": sha, "outcome": "clearly-adult", "reviewer": "Test Person",
            "evidence": "front, side and back in the Studio", "examined": True, **change}


def test_review_routes_are_admin_only(env):
    with env["client"]() as client:
        assert client.get("/v1/admin/reviews").status_code == 401
        assert client.post("/v1/admin/reviews/mira", json=finding(env["sha"])).status_code == 401


def test_an_unreviewed_character_is_pending_not_rejected(env):
    with env["client"]() as client:
        headers = sign_in(client)
        listing = client.get("/v1/admin/reviews", headers=headers).json()
        row = next(r for r in listing["characters"] if r["slug"] == "mira")
        assert row["reviewState"] == "pending"
        assert row["status"] == "needs-review"
        assert row["status"] != "blocked"
        assert row["sha256"] == env["sha"]
        assert row["licence"]["sexualUse"] is True and row["licence"]["modification"] is True
        assert "file" not in row
        assert listing["outcomes"] == ["clearly-adult", "age-ambiguous", "appears-minor", "not-assessable"]


@pytest.mark.parametrize("change, code, reason", [
    ({"examined": False}, 422, "not_examined"),
    ({"outcome": ""}, 422, "outcome_invalid"),
    ({"outcome": "probably-fine"}, 422, "outcome_invalid"),
    ({"sha256": "0" * 64}, 409, "not_this_file"),
])
def test_nothing_is_recorded_without_the_persons_own_finding_for_this_file(env, change, code, reason):
    with env["client"]() as client:
        headers = sign_in(client)
        response = client.post("/v1/admin/reviews/mira", headers=headers, json=finding(env["sha"], **change))
        assert response.status_code == code, response.text
        assert response.json()["detail"]["reason"] == reason
    # Nothing recorded for this file; the committed registry's own entries are the operator's.
    assert env["sha"] not in json.loads(env["registry"].read_text(encoding="utf-8"))["reviews"]


@pytest.mark.parametrize("missing", ["reviewer", "evidence"])
def test_a_blank_name_or_evidence_is_refused(env, missing):
    with env["client"]() as client:
        headers = sign_in(client)
        body = finding(env["sha"])
        body[missing] = ""
        assert client.post("/v1/admin/reviews/mira", headers=headers, json=body).status_code == 422
    # Nothing recorded for this file; the committed registry's own entries are the operator's.
    assert env["sha"] not in json.loads(env["registry"].read_text(encoding="utf-8"))["reviews"]


def test_a_finding_is_recorded_once_and_moves_the_status_on(env):
    with env["client"]() as client:
        headers = sign_in(client)
        response = client.post("/v1/admin/reviews/mira", headers=headers, json=finding(env["sha"]))
        assert response.status_code == 201, response.text
        row = response.json()["character"]
        assert row["reviewState"] == "clearly-adult"
        assert row["status"] != "needs-review"
        entry = json.loads(env["registry"].read_text(encoding="utf-8"))["reviews"][env["sha"]]
        assert entry["reviewer"] == "Test Person" and entry["outcome"] == "clearly-adult"
        again = client.post("/v1/admin/reviews/mira", headers=headers,
                            json=finding(env["sha"], outcome="age-ambiguous", reviewer="Someone Else"))
        assert again.status_code == 409


def test_an_age_ambiguous_finding_is_a_finding_not_a_pending_review(env):
    with env["client"]() as client:
        headers = sign_in(client)
        response = client.post("/v1/admin/reviews/mira", headers=headers,
                               json=finding(env["sha"], outcome="age-ambiguous"))
        assert response.status_code == 201, response.text
        row = response.json()["character"]
        assert row["reviewState"] == "age-ambiguous"
        assert row["status"] == "blocked"


def test_a_replacement_imported_in_the_studio_is_reviewable_like_any_character(env, vrm_bytes):
    """The replacement route: import a new character, then it is on the review screen, pending."""
    def renamed(doc) -> None:
        permitting(doc)
        doc.gltf["extensions"]["VRMC_vrm"]["meta"]["name"] = "Replacement"

    replacement = with_head(edited(vrm_bytes, renamed))  # a generated fixture, not a character
    real = AvatarLibrary.__dict__["from_directory"]
    with env["client"]() as client:
        # make_client pins the library object; an import has to be re-read from disk to appear.
        env["monkeypatch"].setattr(AvatarLibrary, "from_directory", real)
        headers = sign_in(client)
        imported = client.post("/v1/library/import", files={"file": ("Replacement.vrm", replacement,
                                                                     "model/gltf-binary")},
                               data={"presentation": "feminine", "user_attests_modification_allowed": "true"})
        assert imported.status_code == 201, imported.text
        slug = imported.json()["avatar"]["slug"]
        row = next(r for r in client.get("/v1/admin/reviews", headers=headers).json()["characters"]
                   if r["slug"] == slug)
        assert row["reviewState"] == "pending"
        assert row["sha256"] == hashlib.sha256(replacement).hexdigest()
        assert row["licence"]["modification"] is True


async def test_an_imported_bare_file_is_counted_by_the_field_the_list_writes(monkeypatch):
    """CG4 review: register_import lists the state as ``wardrobeState``; reading ``state`` counted
    every accepted bare import as none, so a fixed character kept showing ``needs-body-state``."""
    from apps.api.routes import reviews

    async def listed(_store, _slug):
        return {"looks": [
            {"origin": "operator-import", "wardrobeState": "bare"},
            {"origin": "operator-import", "wardrobeState": "underwear"},
            {"origin": "built", "wardrobeState": "bare"},
        ]}

    monkeypatch.setattr(reviews.prebuilt, "read_list", listed)
    assert await reviews._body_state_files(None, "mira") == 1


DETAIL_EVIDENCE = "packet read; front, side and back looked at in the Studio, adult proportions throughout"


def test_detail_needs_the_finding_the_packet_and_evidence_then_clears_once(env):
    """CG10. Body detail opens only after a clearly-adult finding, Forge's packet for these exact
    bytes, a person's statement that they looked, and 40+ characters of evidence — once."""
    from wardrobe.body_surface.eligibility import detail_clearance

    def detail(headers, **change):
        body = {"sha256": env["sha"], "reviewer": "Test Person", "evidence": DETAIL_EVIDENCE, "examined": True,
                **change}
        return client.post("/v1/admin/reviews/mira/detail", headers=headers, json=body)

    with env["client"]() as client:
        assert client.post("/v1/admin/reviews/mira/packet").status_code == 401
        headers = sign_in(client)
        row = next(r for r in client.get("/v1/admin/reviews", headers=headers).json()["characters"])
        assert row["detail"]["cleared"] is False and row["detail"]["missing"]
        assert {"bareLooks", "detailedLooks", "thumbnails", "packetReady"} <= set(row)
        # No design finding yet: no detail review, packet or not.
        assert client.post("/v1/admin/reviews/mira/packet", headers=headers).status_code == 200
        assert detail(headers).status_code == 409
        assert client.post("/v1/admin/reviews/mira", headers=headers, json=finding(env["sha"])).status_code == 201
        assert detail(headers, evidence="looked").status_code == 409  # under 40 characters
        assert detail(headers, examined=False).status_code == 409
        assert detail(headers, sha256="0" * 64).status_code == 409
        made = client.post("/v1/admin/reviews/mira/packet", headers=headers).json()
        assert made["packet"]["file"]["sha256"] == env["sha"]
        assert made["packet"]["file"]["path"] == "library:mira"  # no server path
        ok = detail(headers)
        assert ok.status_code == 201, ok.text
        assert ok.json()["character"]["detail"]["cleared"] is True
        assert detail(headers, reviewer="Someone Else").status_code == 409  # write-once
    assert detail_clearance(env["registry"].parent, "/nonexistent", env["sha"]) is not None
