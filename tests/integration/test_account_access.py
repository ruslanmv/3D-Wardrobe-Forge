"""AC1 over HTTP: a signed-in account gets a short-lived capability for its own avatars.

The identity provider here is a **test fixture** (``ControlledIdentityProvider``): a table of
credentials and the identities they stand for, plugged in exactly where a deployment plugs in
its real one (``identity_verifier_dependency``). Forge ships no accounts; these tests prove what
the issuing layer does with whatever a verifier answers, and that without one it does nothing.

What must hold:

* no verifier (the default): no capabilities, for anyone, and operator grants unchanged;
* identity comes only from the verified credential: not the body, not an admin session, not a
  grant; and no response ever carries an administrator credential or a secret;
* a capability is short-lived, bound to its account and to the avatars that account is entitled
  to: not another avatar, not another account's looks, not a subset of a refused request;
* it expires by the clock, can be revoked by id or by account at once, and writes nothing.

The avatars are the calibration body with a test box on its head (``tests/support_body_state``).
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from apps.api.routes.access import identity_verifier_dependency
from tests.integration.test_body_state_api import PASSWORD, SECRET, grant_for, permitting, sign_in, upload
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from tests.support_body_state import edited, touch, with_head
from wardrobe.domain.jobs import private_marker
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline import prebuilt
from wardrobe.policy import grants, identity
from wardrobe.policy.identity import AssertionVerifier, Identity

ID_HEADER = identity.HEADER
ID_SECRET = "i" * 40


class ControlledIdentityProvider:
    """A test identity provider: these credentials are these accounts, and nothing else is anyone."""

    configured = True

    def __init__(self) -> None:
        self.accounts = {
            "session-alice": Identity("acct-alice", frozenset({"mira"}), adult=True, issuer="test-idp"),
            "session-bob": Identity("acct-bob", frozenset({"nora"}), adult=True, issuer="test-idp"),
            "session-carol": Identity("acct-carol", frozenset({"mira", "nora"}), adult=True, issuer="test-idp"),
            "session-minor": Identity("acct-young", frozenset({"mira"}), adult=False, issuer="test-idp"),
            "session-empty": Identity("acct-empty", frozenset(), adult=True, issuer="test-idp"),
        }
        self.asked: list[str | None] = []
        self.down = False

    def verify(self, credential):
        self.asked.append(credential)
        if self.down:
            raise RuntimeError("identity provider unreachable")
        return self.accounts.get(credential)


@pytest.fixture
def env(orchestrator, monkeypatch, tmp_path, settings, vrm_bytes):
    mira = with_head(edited(vrm_bytes, permitting))
    settings.wardrobe_grant_secret = SECRET
    library = AvatarLibrary.from_directory(
        write_library(tmp_path / "library", {"Mira.vrm": mira, "Nora.vrm": with_head(edited(vrm_bytes, permitting))}))
    admins = AdminSessions(PASSWORD, ttl_hours=1)
    idp = ControlledIdentityProvider()
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[identity_verifier_dependency] = lambda: idp
    try:
        yield {"client": lambda: make_client(orchestrator, monkeypatch, library), "settings": settings,
               "idp": idp, "mira": mira, "state": edited(mira, touch), "store": orchestrator.store}
    finally:
        for dependency in (admin_sessions_dependency, settings_dependency, identity_verifier_dependency):
            app.dependency_overrides.pop(dependency, None)


def capability(client: TestClient, credential: str | None, *avatars: str, **body):
    headers = {ID_HEADER: credential} if credential is not None else {}
    return client.post("/v1/access/capabilities", headers=headers, json={"avatars": list(avatars), **body})


def as_grant(response) -> dict:
    assert response.status_code == 201, response.text
    return {grants.HEADER: response.json()["token"]}


def private_look(client, env, slug: str = "mira") -> tuple[dict, str, str]:
    """Mira's operator-imported private look. Returns admin headers, look id and asset URL."""
    assert slug == "mira", "only mira has an importable state in this fixture"
    headers = sign_in(client)
    response = upload(client, headers, env["state"], state="lingerie",
                      source=hashlib.sha256(env["mira"]).hexdigest())
    assert response.status_code == 201, response.text
    look = response.json()["look"]
    return headers, look["lookId"], look["vrmUrl"].split("/v1/", 1)[1]


def put_private(client, env, slug: str, look_id: str, *, account: str | None = None) -> str:
    """A private look written straight into the store, optionally one account's own."""
    marker = {"private": True, "wardrobeId": slug, **({"account": account} if account else {})}
    store = env["store"]
    client.portal.call(store.put, private_marker(look_id), json.dumps(marker).encode())
    client.portal.call(store.put, f"looks/{look_id}/look.vrm", f"bytes of {look_id}".encode())
    item = {"lookId": look_id, "templateId": None, "color": None, "foundationColor": None,
            "plan": f"plan-{look_id}", "private": True, "name": look_id, "builtAt": "2026-11-16T00:00:00",
            "vrmUrl": f"/v1/assets/looks/{look_id}/look.vrm", **({"account": account} if account else {})}

    async def add():
        listed = await prebuilt.read_list(store, slug)
        listed["looks"] = [*listed["looks"], item]
        await store.put(prebuilt.wardrobe_key(slug), json.dumps(listed).encode())

    client.portal.call(add)
    return f"assets/looks/{look_id}/look.vrm"


def listed(client, slug: str, headers: dict) -> set[str]:
    return {item["id"] for item in client.get(f"/v1/wardrobes/{slug}", headers=headers).json()["looks"]}


# -- deny by default ---------------------------------------------------------------------------
def test_without_an_identity_verifier_nobody_gets_a_capability(env):
    """The shipped default. Operator grants (BI2) are untouched by it."""
    app.dependency_overrides.pop(identity_verifier_dependency)
    with env["client"]() as client:
        assert client.get("/v1/access").json()["capabilities"] is False
        for credential in (None, "session-alice", AssertionVerifier.sign(ID_SECRET, {"sub": "acct-alice"})):
            refused = capability(client, credential, "mira")
            assert refused.status_code == 503
            assert refused.json()["detail"]["reason"] == "account_access_unavailable"
        headers = sign_in(client)
        assert grant_for(client, headers, "mira")  # BI2 still mints


def test_a_verifier_but_no_grant_secret_is_still_nobody(env):
    env["settings"].wardrobe_grant_secret = ""
    with env["client"]() as client:
        assert client.get("/v1/access").json()["capabilities"] is False
        assert capability(client, "session-alice", "mira").status_code == 503


def test_an_unverified_caller_is_refused_and_a_broken_provider_admits_nobody(env):
    with env["client"]() as client:
        assert client.get("/v1/access").json() == {
            "capabilities": True, "header": ID_HEADER, "grantHeader": grants.HEADER,
            "maxTtlSeconds": grants.ACCOUNT_MAX_TTL_S}
        for credential in (None, "", "session-nobody", "session-alice "):
            refused = capability(client, credential, "mira")
            assert refused.status_code == 401 and refused.json()["detail"]["reason"] == "identity_unverified"
            assert refused.headers["cache-control"] == "no-store"
        env["idp"].down = True
        assert capability(client, "session-alice", "mira").status_code == 401
        env["idp"].down = False
        assert capability(client, "session-alice", "mira").status_code == 201


# -- what a capability is ----------------------------------------------------------------------
def test_a_capability_is_short_lived_and_bound_to_the_account_and_its_avatar(env):
    with env["client"]() as client:
        admin, look_id, url = private_look(client, env, "mira")
        issued = capability(client, "session-alice", "mira")
        body = issued.json()
        assert issued.status_code == 201 and issued.headers["cache-control"] == "no-store"
        assert body["subject"] == "acct-alice" and body["slugs"] == ["mira"] and body["header"] == grants.HEADER
        assert 0 < body["expiresIn"] <= grants.ACCOUNT_MAX_TTL_S == 900
        assert body["expires"] - body["issued"] == body["expiresIn"] == env["settings"].wardrobe_capability_ttl_s
        read = grants.verify(SECRET, body["token"])
        assert read.subject == "acct-alice" and read.slugs == {"mira"}
        token = {grants.HEADER: body["token"]}
        # It reads her private look: listed, and served.
        assert look_id in listed(client, "mira", token)
        assert client.get(f"/v1/{url}", headers=token).content == env["state"]
        assert client.get(f"/v1/{url}").status_code == 404  # nobody else
        # A caller may ask for less time, never more.
        assert capability(client, "session-alice", "mira", ttlSeconds=60).json()["expiresIn"] == 60
        assert capability(client, "session-alice", "mira", ttlSeconds=86400).json()["expiresIn"] == 300
        assert capability(client, "session-alice", "mira", ttlSeconds=1).json()["expiresIn"] == 30
        del admin


def test_identity_comes_from_the_credential_never_from_the_request(env):
    """Not the body, not an admin session, not a grant; and nothing secret comes back."""
    with env["client"]() as client:
        admin = sign_in(client)
        operator_grant = grant_for(client, admin, "mira")
        # The body cannot say who the caller is, or widen what it gets.
        for extra in ({"subject": "acct-alice"}, {"sub": "acct-carol"}, {"adult": True}, {"slugs": ["nora"]}):
            assert capability(client, "session-bob", "nora", **extra).status_code == 422
        # An admin session is not an identity; a grant is not exchangeable for a capability.
        assert client.post("/v1/access/capabilities", headers=admin, json={"avatars": ["mira"]}).status_code == 401
        assert client.post("/v1/access/capabilities", headers=operator_grant,
                           json={"avatars": ["mira"]}).status_code == 401
        mine = as_grant(capability(client, "session-alice", "mira"))
        assert client.post("/v1/access/capabilities", headers=mine, json={"avatars": ["mira"]}).status_code == 401
        # No response of this route carries the admin token, the password or either secret.
        issued = capability(client, "session-alice", "mira")
        for text in (issued.text, json.dumps(dict(issued.headers)), client.get("/v1/access").text,
                     capability(client, "session-nobody", "mira").text):
            for secret in (admin["X-Wardrobe-Admin"], PASSWORD, SECRET, "session-alice"):
                assert secret not in text
        assert env["idp"].asked.count(None) >= 3  # those callers reached the verifier with no credential


def test_a_capability_never_reaches_an_unrelated_avatar(env):
    with env["client"]() as client:
        _admin, mira_look, mira_url = private_look(client, env, "mira")
        nora_url = put_private(client, env, "nora", "look_nora_private")
        alice = as_grant(capability(client, "session-alice", "mira"))
        bob = as_grant(capability(client, "session-bob", "nora"))
        # Each reads its own avatar's private looks and not the other's.
        assert client.get(f"/v1/{mira_url}", headers=alice).status_code == 200
        assert client.get(f"/v1/{nora_url}", headers=alice).status_code == 404
        assert client.get(f"/v1/{nora_url}", headers=bob).status_code == 200
        assert client.get(f"/v1/{mira_url}", headers=bob).status_code == 404
        assert mira_look in listed(client, "mira", alice) and mira_look not in listed(client, "mira", bob)
        assert "look_nora_private" in listed(client, "nora", bob)
        assert "look_nora_private" not in listed(client, "nora", alice)
        assert client.get("/v1/library/nora/prebuilt", headers=alice).json()["count"] == 0
        # Asking for an avatar the account is not entitled to: refused, whole request, no subset.
        for avatars in (("nora",), ("mira", "nora"), ("nora", "mira")):
            refused = capability(client, "session-alice", *avatars)
            assert refused.status_code == 403 and refused.json()["detail"]["reason"] == "not_entitled"
            assert "token" not in refused.text
        assert capability(client, "session-empty", "mira").status_code == 403
        unknown = capability(client, "session-carol", "mira", "ghost")
        assert unknown.status_code == 404 and unknown.json()["detail"]["reason"] == "avatar_not_in_library"
        both = capability(client, "session-carol", "mira", "nora", "mira").json()
        assert both["slugs"] == ["mira", "nora"]


def test_one_accounts_look_is_not_another_accounts(env):
    """Cross-account. A look whose marker names an account is that account's: not another
    account entitled to the same avatar, not an operator grant for her, only it (and an admin)."""
    with env["client"]() as client:
        admin = sign_in(client)
        shared = put_private(client, env, "mira", "look_mira_shared")
        alices = put_private(client, env, "mira", "look_alice_only", account="acct-alice")
        alice = as_grant(capability(client, "session-alice", "mira"))
        carol = as_grant(capability(client, "session-carol", "mira"))  # entitled to mira too
        operator = grant_for(client, admin, "mira")
        for reader, sees in ((alice, True), (carol, False), (operator, False), (admin, True), ({}, False)):
            assert (client.get(f"/v1/{alices}", headers=reader).status_code == 200) is sees
            assert ("look_alice_only" in listed(client, "mira", reader)) is sees
            count = client.get("/v1/library/mira/prebuilt", headers=reader).json()["count"]
            assert count == (2 if sees else 1 if reader else 0)
        # The look private to the avatar, not to an account, is read by all three readers of hers.
        for reader in (alice, carol, operator, admin):
            assert client.get(f"/v1/{shared}", headers=reader).status_code == 200


def test_an_account_not_vouched_adult_gets_nothing(env):
    with env["client"]() as client:
        refused = capability(client, "session-minor", "mira")
        assert refused.status_code == 403
        assert refused.json()["detail"]["reason"] == "adult_verification_required"


# -- expiry and revocation -----------------------------------------------------------------------
def test_a_capability_expires_by_the_clock(env, monkeypatch):
    import time as real_time

    with env["client"]() as client:
        _admin, look_id, url = private_look(client, env, "mira")
        token = as_grant(capability(client, "session-alice", "mira", ttlSeconds=60))
        assert client.get(f"/v1/{url}", headers=token).status_code == 200
        later = real_time.time() + 61
        monkeypatch.setattr(grants.time, "time", lambda: later)
        assert client.get(f"/v1/{url}", headers=token).status_code == 404
        assert look_id not in listed(client, "mira", token)


def test_revoking_a_capability_or_an_account_takes_effect_at_once(env):
    with env["client"]() as client:
        admin, look_id, url = private_look(client, env, "mira")
        first = as_grant(capability(client, "session-alice", "mira"))
        second = as_grant(capability(client, "session-alice", "mira"))
        carol = as_grant(capability(client, "session-carol", "mira"))
        # Only an admin session revokes.
        for who in ({}, first):
            assert client.post("/v1/admin/access/revocations", headers=who,
                               json={"subject": "acct-carol"}).status_code == 401
        assert client.post("/v1/admin/access/revocations", headers=admin, json={}).status_code == 422
        assert client.post("/v1/admin/access/revocations", headers=admin,
                           json={"token": "not-a-token"}).status_code == 422
        # One capability, by presenting it: that one dies, the account's other one lives.
        revoked = client.post("/v1/admin/access/revocations", headers=admin,
                              json={"token": first[grants.HEADER], "reason": "copied"})
        assert revoked.status_code == 201 and revoked.json()["id"] == grants.verify(SECRET, first[grants.HEADER]).id
        assert client.get(f"/v1/{url}", headers=first).status_code == 404
        assert look_id not in listed(client, "mira", first)
        assert client.get(f"/v1/{url}", headers=second).status_code == 200
        # The account: every capability it holds, and every one it asks for.
        assert client.post("/v1/admin/access/revocations", headers=admin,
                           json={"subject": "acct-alice", "reason": "left"}).status_code == 201
        assert client.get(f"/v1/{url}", headers=second).status_code == 404
        refused = capability(client, "session-alice", "mira")
        assert refused.status_code == 403 and refused.json()["detail"]["reason"] == "account_revoked"
        assert client.get(f"/v1/{url}", headers=carol).status_code == 200  # another account is untouched
        state = client.get("/v1/admin/access/revocations", headers=admin).json()
        assert list(state["subjects"]) == ["acct-alice"] and len(state["ids"]) == 1
        assert client.get("/v1/admin/access/revocations").status_code == 401
        assert client.get("/v1/assets/access/revocations.json", headers=admin).status_code == 404
        # Restored: it may be issued capabilities again; the old ones stay as dead as they were made.
        assert client.delete("/v1/admin/access/revocations/subjects/acct-alice", headers=admin).status_code == 204
        assert client.delete("/v1/admin/access/revocations/subjects/acct-alice", headers=admin).status_code == 404
        assert client.get(f"/v1/{url}", headers=as_grant(capability(client, "session-alice", "mira"))).status_code == 200
        assert client.get(f"/v1/{url}", headers=first).status_code == 404
        # The operator's environment list works for accounts too.
        env["settings"].wardrobe_account_revoked = "acct-carol"
        assert client.get(f"/v1/{url}", headers=carol).status_code == 404
        assert capability(client, "session-carol", "mira").status_code == 403


def test_a_capability_writes_nothing(env):
    with env["client"]() as client:
        _admin, look_id, _url = private_look(client, env, "mira")
        token = as_grant(capability(client, "session-alice", "mira"))
        digest = hashlib.sha256(env["mira"]).hexdigest()
        assert upload(client, token, env["state"], state="lingerie", source=digest).status_code == 401
        assert client.post("/v1/admin/grants", headers=token, json={"slugs": ["mira"]}).status_code == 401
        assert client.put("/v1/admin/declarations/mira", headers=token,
                          json={"depictsAdult": True, "ageConfirmed": True}).status_code == 401
        assert client.delete(f"/v1/admin/library/mira/body-states/{look_id}", headers=token).status_code == 401
        assert client.get("/v1/admin/library/mira/withdrawals", headers=token).status_code == 401
        assert client.get("/v1/admin", headers=token).json()["signedIn"] is False


# -- the shipped verifier, end to end ------------------------------------------------------------
def test_a_trusted_backends_assertion_is_exchanged_for_a_capability(env, monkeypatch):
    """``WARDROBE_IDENTITY_VERIFIER=assertion``: the app's server signs who is signed in; Forge
    checks it with a secret no browser holds. The backend here is the test, holding ID_SECRET."""
    import time as real_time

    app.dependency_overrides.pop(identity_verifier_dependency)
    settings = env["settings"]
    settings.wardrobe_identity_verifier = "assertion"
    settings.wardrobe_identity_secret = ID_SECRET
    settings.wardrobe_identity_issuers = "nexus-app"
    now = int(real_time.time())

    def assertion(secret: str = ID_SECRET, **over) -> str:
        claims = {"iss": "nexus-app", "aud": "wardrobe-forge", "sub": "acct-alice", "iat": now, "exp": now + 120,
                  "avatars": ["mira"], "adult": True, **over}
        return AssertionVerifier.sign(secret, claims)

    with env["client"]() as client:
        _admin, _look, url = private_look(client, env, "mira")
        token = as_grant(capability(client, assertion(), "mira"))
        assert grants.verify(SECRET, token[grants.HEADER]).subject == "acct-alice"
        assert client.get(f"/v1/{url}", headers=token).status_code == 200
        assert capability(client, assertion(), "nora").status_code == 403           # not in the assertion
        assert capability(client, assertion(adult=False), "mira").status_code == 403
        assert capability(client, assertion(aud="other"), "mira").status_code == 401
        assert capability(client, assertion(iss="stranger"), "mira").status_code == 401
        assert capability(client, assertion(exp=now - 1), "mira").status_code == 401
        assert capability(client, assertion("z" * 40), "mira").status_code == 401  # signed by nobody we trust
        # The grant secret cannot sign identities: the two secrets are different on purpose.
        assert capability(client, assertion(SECRET), "mira").status_code == 401
        # Misconfigured (the same secret for both): no capabilities at all.
        settings.wardrobe_identity_secret = SECRET
        assert capability(client, assertion(SECRET), "mira").status_code == 503
