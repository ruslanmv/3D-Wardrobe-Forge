"""The Studio's admin session: a per-avatar declaration for one session, and privacy for what it makes.

What must hold, whatever the Studio does with it:

* no password, no admin — and a short one is refused, not accepted;
* signing in unlocks nothing: an avatar is unlocked only by a declaration for it;
* the model's own terms still win over any declaration;
* whatever relied on a session's declaration is invisible without one — job,
  look, files, wardrobe entry, export — and a caller cannot mark its own work private.

The avatar declared here is the medium calibration body, which
``assets/calibration/policy.json`` declares adult: these tests exercise the
declaration mechanism, not a judgement about anyone's avatar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.admin import MIN_PASSWORD_LENGTH, AdminSessions, admin_sessions_dependency
from apps.api.main import app
from tests.integration.test_studio_api import make_client, wait_for
from tests.library_support import write_library
from wardrobe.library import AvatarLibrary
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.document import GltfDocument

PASSWORD = "correct horse battery staple"
BIKINI = "red triangle bikini"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def admins(clock) -> AdminSessions:
    return AdminSessions(PASSWORD, ttl_hours=1, clock=clock)


def disallowing(vrm0: bytes) -> bytes:
    """The same body, with its author's terms forbidding sexual use."""
    document = GltfDocument.from_bytes(vrm0)
    document.gltf["extensions"]["VRM"]["meta"]["sexualUssageName"] = "Disallow"
    return document.to_bytes()


@pytest.fixture
def client(orchestrator, monkeypatch, tmp_path, vrm_bytes, vrm0_bytes, admins):
    assert declared_adult("calibration-b-medium")
    library = AvatarLibrary.from_directory(
        write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes, "Nora.vrm": vrm_bytes,
                                             "Vera.vrm": disallowing(vrm0_bytes)})
    )
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    try:
        with make_client(orchestrator, monkeypatch, library) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)


def sign_in(client: TestClient) -> dict:
    response = client.post("/v1/admin/session", json={"password": PASSWORD})
    assert response.status_code == 201, response.text
    return {"X-Wardrobe-Admin": response.json()["token"]}


def declare(client: TestClient, headers: dict, slug: str, value: bool = True):
    return client.put(f"/v1/admin/declarations/{slug}", json={"depictsAdult": value}, headers=headers)


def dress(client: TestClient, slug: str, prompt: str, headers: dict | None = None, **body) -> dict:
    payload = {"outfit": {"prompt": prompt, "mode": "template"},
               "options": {"renderPreview": False, "engine": "native"}, **body}
    response = client.post(f"/v1/library/{slug}/jobs", json=payload, headers=headers or {})
    assert response.status_code == 202, response.text
    return wait_for_as(client, response.json()["id"], headers or {})


def wait_for_as(client: TestClient, job_id: str, headers: dict) -> dict:
    original = client.get

    def get(url, **kwargs):
        return original(url, headers={**headers, **kwargs.pop("headers", {})}, **kwargs)

    client.get = get
    try:
        return wait_for(client, job_id)
    finally:
        client.get = original


# ----------------------------------------------------------------------
# sign-in
# ----------------------------------------------------------------------
def test_without_a_password_there_is_no_admin(orchestrator, monkeypatch, tmp_path, vrm_bytes):
    library = AvatarLibrary.from_directory(write_library(tmp_path / "lib", {"Mira.vrm": vrm_bytes}))
    for password in ("", "x" * (MIN_PASSWORD_LENGTH - 1)):
        app.dependency_overrides[admin_sessions_dependency] = lambda p=password: AdminSessions(p)
        try:
            with make_client(orchestrator, monkeypatch, library) as client:
                assert client.get("/v1/admin").json()["enabled"] is False
                assert client.post("/v1/admin/session", json={"password": password or "x"}).status_code == 404
        finally:
            app.dependency_overrides.pop(admin_sessions_dependency, None)


def test_a_wrong_password_is_refused_and_repeated_failures_are_throttled(client: TestClient, clock: Clock):
    for _ in range(5):
        assert client.post("/v1/admin/session", json={"password": "guess"}).status_code == 401
    # Even the right password waits out the window.
    assert client.post("/v1/admin/session", json={"password": PASSWORD}).status_code == 429
    clock.now += 16 * 60
    assert client.post("/v1/admin/session", json={"password": PASSWORD}).status_code == 201


def test_a_session_expires_and_signing_out_ends_it(client: TestClient, clock: Clock):
    headers = sign_in(client)
    assert client.get("/v1/admin", headers=headers).json()["signedIn"] is True
    clock.now += 2 * 3600
    assert client.get("/v1/admin", headers=headers).json()["signedIn"] is False

    headers = sign_in(client)
    assert client.delete("/v1/admin/session", headers=headers).status_code == 204
    assert client.get("/v1/admin", headers=headers).json()["signedIn"] is False
    assert declare(client, headers, "mira").status_code == 401


def test_declaring_needs_a_session_and_a_library_avatar(client: TestClient):
    assert declare(client, {}, "mira").status_code == 401
    assert declare(client, {"X-Wardrobe-Admin": "forged"}, "mira").status_code == 401
    assert declare(client, sign_in(client), "nobody").status_code == 404


# ----------------------------------------------------------------------
# the declaration
# ----------------------------------------------------------------------
def test_signing_in_unlocks_nothing_and_a_declaration_unlocks_only_its_avatar(client: TestClient):
    headers = sign_in(client)
    assert dress(client, "mira", BIKINI, headers)["reason"] == "requires_adult_declaration"

    assert declare(client, headers, "mira").json()["declared"] == ["mira"]
    listing = {a["slug"]: a for a in client.get("/v1/library", headers=headers).json()["avatars"]}
    assert (listing["mira"]["depictsAdult"], listing["mira"]["declaredBy"]) == (True, "session")
    assert listing["nora"]["depictsAdult"] is False

    assert dress(client, "mira", BIKINI, headers)["state"] == "completed"
    assert dress(client, "nora", BIKINI, headers)["reason"] == "requires_adult_declaration"
    # The same request without the session: the gate never heard of it.
    assert dress(client, "mira", BIKINI)["reason"] == "requires_adult_declaration"
    public = {a["slug"]: a for a in client.get("/v1/library").json()["avatars"]}
    assert public["mira"]["depictsAdult"] is False and public["mira"]["declaredBy"] is None


def test_the_models_own_terms_still_win_over_a_declaration(client: TestClient):
    headers = sign_in(client)
    declare(client, headers, "vera")
    job = dress(client, "vera", BIKINI, headers)
    assert job["state"] == "rejected" and job["reason"] == "intimate_garments_not_permitted_by_model"


def test_withdrawing_a_declaration_or_signing_out_locks_the_avatar_again(client: TestClient):
    headers = sign_in(client)
    declare(client, headers, "mira")
    declare(client, headers, "mira", False)
    assert dress(client, "mira", BIKINI, headers)["reason"] == "requires_adult_declaration"

    declare(client, headers, "mira")
    client.delete("/v1/admin/session", headers=headers)
    fresh = sign_in(client)
    assert client.get("/v1/admin", headers=fresh).json()["session"]["declared"] == []
    assert dress(client, "mira", BIKINI, fresh)["reason"] == "requires_adult_declaration"


# ----------------------------------------------------------------------
# privacy
# ----------------------------------------------------------------------
def test_what_a_session_makes_is_invisible_without_one(client: TestClient):
    headers = sign_in(client)
    declare(client, headers, "mira")
    public_look = dress(client, "mira", "black pencil skirt")  # made by the public: stays public
    job = dress(client, "mira", BIKINI, headers)
    assert job["state"] == "completed" and job["request"]["options"]["private"] is True
    look_id = job["look"]["id"]

    # Nowhere without the session...
    assert job["id"] not in {j["id"] for j in client.get("/v1/jobs").json()}
    assert client.get(f"/v1/jobs/{job['id']}").status_code == 404
    assert client.get(f"/v1/jobs/{job['id']}/events").status_code == 404
    assert client.get(f"/v1/looks/{look_id}").status_code == 404
    wardrobe = {look["id"] for look in client.get("/v1/wardrobes/mira").json()["looks"]}
    assert look_id not in wardrobe and public_look["look"]["id"] in wardrobe
    assert look_id not in client.get("/v1/wardrobes/mira/avatars.json").text
    for name in ("look.vrm", "fit-report.json", "private.json"):
        assert client.get(f"/v1/assets/looks/{look_id}/{name}").status_code == 404, name
    assert look_id not in client.get("/v1/assets/wardrobes/mira/wardrobe.json").text
    bundle = client.get("/v1/wardrobes/mira/bundle.zip")
    assert bundle.status_code == 200 and look_id not in bundle.content.decode("latin-1")
    assert client.delete(f"/v1/wardrobes/mira/looks/{look_id}").status_code == 404
    assert client.post("/v1/library/mira/jobs", json={"outfit": {"prompt": "white crop top"},
                                                      "baseLookId": look_id}).status_code == 404

    # ...and all there with it.
    assert client.get(f"/v1/jobs/{job['id']}", headers=headers).status_code == 200
    assert client.get(f"/v1/looks/{look_id}", headers=headers).status_code == 200
    assert look_id in {look["id"] for look in client.get("/v1/wardrobes/mira", headers=headers).json()["looks"]}
    assert client.get(f"/v1/assets/looks/{look_id}/look.vrm", headers=headers).status_code == 200
    assert look_id in client.get("/v1/wardrobes/mira/bundle.zip", headers=headers).content.decode("latin-1")


def test_a_set_built_on_a_private_look_is_private(client: TestClient):
    headers = sign_in(client)
    declare(client, headers, "mira")
    base = dress(client, "mira", BIKINI, headers)
    declare(client, headers, "mira", False)  # the top itself needs no declaration...
    top = dress(client, "mira", "white crop top", headers, baseLookId=base["look"]["id"])
    assert top["state"] == "completed"
    assert top["request"]["options"]["private"] is True  # ...but it is worn over a private look


def test_a_caller_cannot_mark_its_own_work_private(client: TestClient, stored_avatar):
    job = dress(client, "mira", "black pencil skirt", options={"private": True, "renderPreview": False})
    assert job["request"]["options"]["private"] is False
    response = client.post("/v1/jobs", json={
        "avatar": {"storageKey": stored_avatar, "license": {"conditionsOfUse": {"modification": "allow"}}},
        "outfit": {"prompt": "black pencil skirt", "mode": "template"},
        "options": {"private": True, "renderPreview": False},
    })
    assert response.json()["request"]["options"]["private"] is False
