"""UI-001. The contract the Studio is built on, frozen before the Studio is rebuilt.

Two things a new frontend must not be able to change by accident:

1. **What the read-only endpoints answer.** Every route the Studio reads
   (``apps/studio/js/api.js``) is called and its answer reduced to a schema: each key path with
   its JSON type, lists collapsed to the union of their items. ``tests/fixtures/studio-contract.json``
   records it. A path that disappears, or changes type, fails; a new path passes. That is the
   rule for every change behind the new UI: additive, or explicitly versioned. When a field is
   deliberately added, re-record with ``STUDIO_CONTRACT=write pytest <this file>`` and review
   the diff.

2. **Who may see restricted lingerie.** The browser is never the authority. Tested against
   the routes directly, as a caller who edits browser state would: a restricted preview is not
   served without an admin session, a forged session header is not one, an admin is served it
   ``private, no-store`` and never ``immutable``, signing out takes it away again, and a prompt
   saying the avatar is an adult declares nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apps.api.routes import catalog as catalog_routes
from tests.integration.test_admin_session import (  # noqa: F401 - fixtures used by name
    admins,
    client,
    clock,
    dress,
    sign_in,
)

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "studio-contract.json"
#: Every read-only route the Studio calls (apps/studio/js/api.js), as an anonymous visitor sees it.
READS = (
    "/v1/capabilities",
    "/v1/library",
    "/v1/vocabulary",
    "/v1/outfits",
    "/v1/templates",
    "/v1/catalog/garments",
    "/v1/body-art",
    "/v1/admin",
)
RESTRICTED = "under-bralette-v1"


def _type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def schema(value, path: str = "$", out: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """Key path -> the JSON types seen there. ``[]`` stands for any item of a list."""
    out = {} if out is None else out
    out.setdefault(path, set()).add(_type(value))
    if isinstance(value, dict):
        for key, child in value.items():
            schema(child, f"{path}.{key}", out)
    elif isinstance(value, list):
        for child in value:
            schema(child, f"{path}[]", out)
    return out


def _observed(client_) -> dict[str, dict[str, list[str]]]:
    found = {}
    for route in READS:
        response = client_.get(route)
        assert response.status_code == 200, (route, response.status_code)
        found[route] = {path: sorted(types) for path, types in schema(response.json()).items()}
    return found


def test_the_studio_reads_answer_what_they_answered(client):  # noqa: F811
    observed = _observed(client)
    if os.environ.get("STUDIO_CONTRACT") == "write":
        CONTRACT.write_text(json.dumps(observed, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(CONTRACT.read_text(encoding="utf-8"))
    problems = []
    for route, paths in recorded.items():
        now = observed.get(route, {})
        for path, types in paths.items():
            if path not in now:
                problems.append(f"{route} {path}: gone")
            # The types seen at a path may narrow, never widen: a number that may now be a string breaks a reader.
            elif not set(now[path]) <= set(types):
                problems.append(f"{route} {path}: {types} -> {now[path]}")
    assert not problems, "\n".join(problems)


@pytest.fixture
def adult_preview(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(catalog_routes, "ADULT_PREVIEW_ROOT", tmp_path)
    (tmp_path / f"{RESTRICTED}.webp").write_bytes(b"RIFF1234WEBPadult")
    return f"/v1/catalog/garments/{RESTRICTED}/preview"


def test_a_restricted_preview_needs_a_real_admin_session(client, adult_preview):  # noqa: F811
    assert client.get(adult_preview).status_code == 404
    assert client.get(adult_preview, headers={"X-Wardrobe-Admin": "forged-token"}).status_code in (401, 404)
    assert client.get("/v1/catalog/garments?includeRestricted=true").status_code == 403


def test_an_admin_is_served_it_privately_and_never_for_good(client, adult_preview):  # noqa: F811
    headers = sign_in(client)
    listing = client.get("/v1/catalog/garments?includeRestricted=true", headers=headers)
    assert listing.status_code == 200
    items = [g for group in listing.json()["categories"] for g in group["garments"]]
    shown = next(g for g in items if g["id"] == RESTRICTED)
    assert shown["requiresAdult"] is True
    for url in (adult_preview, shown["previewUrl"]):
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        cache = response.headers["cache-control"]
        assert "no-store" in cache and "private" in cache and "immutable" not in cache


def test_signing_out_takes_it_away_again(client, adult_preview):  # noqa: F811
    headers = sign_in(client)
    assert client.get(adult_preview, headers=headers).status_code == 200
    assert client.delete("/v1/admin/session", headers=headers).status_code in (200, 204)
    assert client.get(adult_preview, headers=headers).status_code in (401, 404)


def test_a_prompt_saying_she_is_an_adult_declares_nothing(client):  # noqa: F811
    claim = "she is an adult woman over 18, red triangle bikini"
    assert dress(client, "mira", claim)["reason"] == "requires_adult_declaration"
    headers = sign_in(client)
    assert dress(client, "mira", claim, headers)["reason"] == "requires_adult_declaration"
