"""UI-006. GET /v1/catalog/garments/{id}/parameters: answered as the garment's preview is gated."""

from __future__ import annotations

from tests.integration.test_admin_session import (  # noqa: F401 - fixtures used by name
    admins,
    client,
    clock,
    sign_in,
)

PUBLIC = "/v1/catalog/garments/dress-mini-bodycon-v1/parameters"
RESTRICTED = "/v1/catalog/garments/under-thong-v2/parameters"


def test_a_public_garment_answers_anyone_and_may_be_cached_briefly(client):  # noqa: F811
    response = client.get(PUBLIC)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    assert body["schemaVersion"] == 1 and body["templateId"] == "dress-mini-bodycon-v1"
    assert body["requiresAdult"] is False
    assert [g["adjustable"] for g in body["groups"]][:1] == [True]


def test_a_restricted_garment_is_not_there_without_a_session(client):  # noqa: F811
    assert client.get(RESTRICTED).status_code == 404
    assert client.get(RESTRICTED, headers={"X-Wardrobe-Admin": "forged"}).status_code in (401, 404)


def test_an_admin_gets_it_privately(client):  # noqa: F811
    response = client.get(RESTRICTED, headers=sign_in(client))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["requiresAdult"] is True
    assert any(g["id"] == "lingerie.brief" for g in response.json()["groups"])


def test_an_unknown_garment_is_a_404(client):  # noqa: F811
    assert client.get("/v1/catalog/garments/no-such-thing/parameters").status_code == 404
