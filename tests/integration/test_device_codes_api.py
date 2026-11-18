"""DC1 over HTTP: an admin session issues a device code; a device trades it once for the grant.

What must hold: only an admin session issues; the redeemed grant is exactly a read grant (it reads
the avatar it names and nothing else, and verifies like a pasted one); a code redeems once; wrong
codes all look the same; guessing is rate-limited; and with no grant secret there are no codes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from apps.api.routes import device_codes as route
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from tests.support_body_state import with_head
from wardrobe.library import AvatarLibrary
from wardrobe.policy import device_codes, grants

PASSWORD = "correct horse battery staple"
SECRET = "s" * 40


@pytest.fixture
def env(orchestrator, monkeypatch, tmp_path, settings, vrm_bytes):
    settings.wardrobe_grant_secret = SECRET
    library = AvatarLibrary.from_directory(
        write_library(tmp_path / "library", {"Mira.vrm": with_head(vrm_bytes), "Nora.vrm": vrm_bytes}))
    admins = AdminSessions(PASSWORD, ttl_hours=1)
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    app.dependency_overrides[settings_dependency] = lambda: settings
    device_codes.codes.reset()
    route.attempts.reset()
    try:
        yield {"client": lambda: make_client(orchestrator, monkeypatch, library), "settings": settings}
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)
        app.dependency_overrides.pop(settings_dependency, None)
        device_codes.codes.reset()
        route.attempts.reset()


def admin(client: TestClient) -> dict:
    token = client.post("/v1/admin/session", json={"username": "admin", "password": PASSWORD}).json()["token"]
    return {"X-Wardrobe-Admin": token}


def issue(client, headers, slugs=("mira",), ttl=3600):
    return client.post("/v1/admin/device-codes", headers=headers, json={"slugs": list(slugs), "ttlSeconds": ttl})


def test_only_an_admin_session_issues_codes(env):
    with env["client"]() as client:
        assert issue(client, {}).status_code == 401


def test_a_code_is_traded_once_for_a_working_read_grant(env):
    with env["client"]() as client:
        issued = issue(client, admin(client))
        assert issued.status_code == 201, issued.text
        body = issued.json()
        assert len(body["code"]) == 7 and body["code"][3] == "-"
        assert "token" not in body and "token" not in body["grant"]  # the grant leaves only on redeem
        typed = body["code"].lower().replace("-", " ")
        redeemed = client.post("/v1/device-codes/redeem", json={"code": typed})
        assert redeemed.status_code == 200, redeemed.text
        grant = grants.verify(SECRET, redeemed.json()["token"])
        assert grant is not None and grant.slugs == frozenset({"mira"})
        assert redeemed.json()["id"] == body["grant"]["id"]
        again = client.post("/v1/device-codes/redeem", json={"code": body["code"]})
        assert again.status_code == 404


def test_every_wrong_code_answers_the_same(env):
    with env["client"]() as client:
        issue(client, admin(client))
        answers = {client.post("/v1/device-codes/redeem", json={"code": c}).json()["detail"]["reason"]
                   for c in ("ZZZ-ZZZ", "abc", "K7P-4QXX")}
        assert answers == {"device_code_invalid"}


def test_guessing_is_rate_limited(env):
    with env["client"]() as client:
        for _ in range(route.ATTEMPTS_PER_MINUTE):
            assert client.post("/v1/device-codes/redeem", json={"code": "ZZZ-ZZZ"}).status_code == 404
        limited = client.post("/v1/device-codes/redeem", json={"code": "ZZZ-ZZZ"})
        assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_no_grant_secret_means_no_codes(env):
    env["settings"].wardrobe_grant_secret = None
    with env["client"]() as client:
        assert issue(client, admin(client)).json()["detail"]["reason"] == "grants_unavailable"
        assert device_codes.codes.pending() == 0


def test_a_code_names_only_library_avatars(env):
    with env["client"]() as client:
        assert issue(client, admin(client), slugs=("nobody",)).status_code == 404
