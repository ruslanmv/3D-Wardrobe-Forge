"""F5. A keyed deployment still lets yourfriend.online and its own Studio in, without the key.

The key is for callers that can keep a secret (a server). yourfriend.online is a
public page and cannot, and the Studio a Space serves is that Space: asking either
for a key made the try-on haul stop at a question its user could not answer. A
page on any other site, and any caller with a wrong key, is still refused.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import settings_dependency
from apps.api.main import app
from wardrobe.config import Settings
from wardrobe.pipeline import orchestrator as orchestrator_module


@pytest.fixture
def keyed(orchestrator, monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    settings = Settings(_env_file=None, wardrobe_auth_mode="api_key", wardrobe_api_key="server-secret",
                        wardrobe_storage_root=str(tmp_path))
    app.dependency_overrides[settings_dependency] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client, settings
    finally:
        app.dependency_overrides.pop(settings_dependency, None)


def test_yourfriend_online_needs_no_key(keyed):
    client, _ = keyed
    assert client.get("/v1/templates", headers={"Origin": "https://yourfriend.online"}).status_code == 200
    assert client.get("/v1/templates", headers={"Origin": "https://www.yourfriend.online/"}).status_code == 200
    auth = client.get("/v1/capabilities", headers={"Origin": "https://yourfriend.online"}).json()["auth"]
    assert auth == {"mode": "api_key", "keyRequired": False, "trusted": "origin"}


def test_the_studio_this_space_serves_needs_no_key(keyed):
    client, _ = keyed
    same_host = {"Origin": "http://testserver"}
    assert client.get("/v1/templates", headers=same_host).status_code == 200
    assert client.get("/v1/templates", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.get("/v1/capabilities", headers=same_host).json()["auth"]["keyRequired"] is False


def test_any_other_page_or_a_wrong_key_is_refused(keyed):
    client, _ = keyed
    for headers in ({}, {"Origin": "https://example.com"}, {"Origin": "https://yourfriend.online.example.com"},
                    {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
                    {"Origin": "https://example.com", "Authorization": "Bearer wrong"}):
        assert client.get("/v1/templates", headers=headers).status_code == 401, headers
    assert client.get("/v1/capabilities", headers={"Origin": "https://example.com"}).json()["auth"]["keyRequired"]


def test_the_key_still_works_from_anywhere(keyed):
    client, _ = keyed
    headers = {"Origin": "https://example.com", "Authorization": "Bearer server-secret"}
    assert client.get("/v1/templates", headers=headers).status_code == 200


def test_the_fallback_can_be_narrowed(keyed):
    client, settings = keyed
    settings.wardrobe_trusted_origins = []
    settings.wardrobe_trust_same_origin = False
    assert client.get("/v1/templates", headers={"Origin": "https://yourfriend.online"}).status_code == 401
    assert client.get("/v1/templates", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 401


def test_an_open_deployment_asks_nobody_for_a_key(orchestrator, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    with TestClient(app) as client:
        assert client.get("/v1/capabilities").json()["auth"]["keyRequired"] is False
