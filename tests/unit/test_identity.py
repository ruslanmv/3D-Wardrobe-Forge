"""AC1. Capabilities, the identity seam, and revocation: the rules, without HTTP.

Every test here is a way in that must stay shut: a token that outlives its class, a statement
nobody signed, a verifier that is absent, broken or lying about its type, a revocation list
nobody can read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import types

import pytest

from wardrobe.policy import grants, identity, revocations
from wardrobe.policy.identity import AssertionVerifier, DenyAll, Identity
from wardrobe.storage.object_store import LocalObjectStore

GRANT_SECRET = "g" * 40
ID_SECRET = "i" * 40
NOW = 1_800_000_000


def _claims(**over) -> dict:
    base = {"iss": "nexus-app", "aud": "wardrobe-forge", "sub": "acct-alice", "iat": NOW, "exp": NOW + 120,
            "avatars": ["mira"], "adult": True}
    return {**base, **over}


def _verifier(**kw) -> AssertionVerifier:
    return AssertionVerifier(ID_SECRET, audience="wardrobe-forge", issuers={"nexus-app"}, **kw)


# -- capabilities ---------------------------------------------------------------------------
def test_a_capability_is_bound_to_its_account_and_its_avatars():
    token, grant = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-alice", now=NOW)
    read = grants.verify(GRANT_SECRET, token, now=NOW + 10)
    assert read.subject == "acct-alice" and read.slugs == {"mira"} and read.expires == NOW + 300
    assert read.covers("mira") and not read.covers("nora") and not read.covers(None)
    # A look that names an account is that account's alone.
    assert read.covers("mira", "acct-alice") and not read.covers("mira", "acct-bob")
    assert grant.to_dict()["subject"] == "acct-alice"


def test_an_operator_grant_reads_no_account_bound_look():
    token, _ = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=3600, now=NOW)
    grant = grants.verify(GRANT_SECRET, token, now=NOW + 10)
    assert grant.subject is None and "subject" not in grant.to_dict()
    assert grant.covers("mira") and not grant.covers("mira", "acct-alice")


@pytest.mark.parametrize("ttl", [1, 29, grants.ACCOUNT_MAX_TTL_S + 1, 3600, grants.MAX_TTL_S])
def test_a_capability_cannot_be_minted_long_or_instant(ttl):
    with pytest.raises(grants.GrantError):
        grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=ttl, subject="acct-alice")


@pytest.mark.parametrize("subject", ["", " ", "a b", "x" * 200, "évil", "a\nb", 7])
def test_a_capability_names_a_plain_bounded_account_id(subject):
    with pytest.raises(grants.GrantError):
        grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject=subject)


def test_a_signed_long_lived_token_with_an_account_on_it_does_not_verify():
    """Even correctly signed: an issuer that hands out a month with someone's name on it is refused
    at the reader, not only at the mint."""
    claims = {"v": grants.VERSION, "scope": grants.SCOPE, "jti": "abc", "slugs": ["mira"], "iat": NOW,
              "exp": NOW + 86400, "label": "", "sub": "acct-alice"}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    mac = hmac.new(GRANT_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    token = f"{body}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    assert grants.verify(GRANT_SECRET, token, now=NOW + 10) is None
    claims.pop("sub")  # the same token without a name is an ordinary one-day operator grant
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    mac = hmac.new(GRANT_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    token = f"{body}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    assert grants.verify(GRANT_SECRET, token, now=NOW + 10).subject is None


def test_a_capability_expires():
    token, _ = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=60, subject="acct-alice", now=NOW)
    assert grants.verify(GRANT_SECRET, token, now=NOW + 59) is not None
    assert grants.verify(GRANT_SECRET, token, now=NOW + 60) is None
    assert grants.verify("x" * 40, token, now=NOW + 1) is None


# -- the assertion verifier -----------------------------------------------------------------
def test_a_trusted_backends_statement_is_an_identity():
    who = _verifier().verify(AssertionVerifier.sign(ID_SECRET, _claims()), now=NOW + 5)
    assert who == Identity("acct-alice", frozenset({"mira"}), True, "nexus-app")


@pytest.mark.parametrize("change", [
    {"exp": NOW - 1},                      # expired
    {"iat": NOW + 600, "exp": NOW + 700},  # from the future
    {"exp": NOW + 3600},                   # an assertion is not a session
    {"exp": NOW},                          # no life at all
    {"aud": "another-service"},
    {"iss": "someone-else"},
    {"iss": None},
    {"sub": ""},
    {"sub": "a b"},
    {"avatars": "mira"},
    {"avatars": ["Mira!"]},
    {"avatars": [f"a{i}" for i in range(40)]},
])
def test_a_statement_with_the_wrong_claims_is_nobody(change):
    assert _verifier().verify(AssertionVerifier.sign(ID_SECRET, _claims(**change)), now=NOW + 5) is None


def test_adult_is_only_ever_the_literal_true():
    for value in (None, "true", 1, "yes"):
        who = _verifier().verify(AssertionVerifier.sign(ID_SECRET, _claims(adult=value)), now=NOW + 5)
        assert who is not None and who.adult is False
    missing = {k: v for k, v in _claims().items() if k != "adult"}
    assert _verifier().verify(AssertionVerifier.sign(ID_SECRET, missing), now=NOW + 5).adult is False


def _forged(header: dict, claims: dict, secret: str | None) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    head, body = enc(header), enc(claims)
    if secret is None:
        return f"{head}.{body}."
    mac = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"


def test_a_statement_nobody_signed_is_nobody():
    good = AssertionVerifier.sign(ID_SECRET, _claims())
    head, body, signature = good.split(".")
    verify = lambda token: _verifier().verify(token, now=NOW + 5)  # noqa: E731
    assert verify(good) is not None
    assert verify(AssertionVerifier.sign("z" * 40, _claims())) is None           # another secret
    assert verify(_forged({"alg": "none"}, _claims(), None)) is None             # "no signature needed"
    assert verify(_forged({"alg": "none"}, _claims(), ID_SECRET)) is None
    assert verify(_forged({"alg": "HS512"}, _claims(), ID_SECRET)) is None       # only one algorithm
    assert verify(f"{head}.{body}.{signature[:-2]}AA") is None                   # tampered signature
    other = AssertionVerifier.sign(ID_SECRET, _claims(sub="acct-bob")).split(".")[1]
    assert verify(f"{head}.{other}.{signature}") is None                         # another account's body
    for junk in (None, "", "a.b", "a.b.c.d", "not a token", "x" * 9000, good + "x"):
        assert verify(junk) is None


def test_the_verifier_needs_a_real_secret_and_an_audience():
    with pytest.raises(ValueError):
        AssertionVerifier("short", audience="wardrobe-forge")
    with pytest.raises(ValueError):
        AssertionVerifier(ID_SECRET, audience="")


# -- loading: every mistake is "nobody" -------------------------------------------------------
def _settings(**over):
    base = {"wardrobe_identity_verifier": "", "wardrobe_identity_secret": ID_SECRET,
            "wardrobe_identity_audience": "wardrobe-forge", "wardrobe_identity_issuers": "nexus-app",
            "wardrobe_grant_secret": GRANT_SECRET}
    return types.SimpleNamespace(**{**base, **over})


def test_no_verifier_is_the_default_and_denies_everyone():
    verifier = identity.load_verifier(_settings())
    assert isinstance(verifier, DenyAll) and verifier.configured is False
    assert verifier.verify(AssertionVerifier.sign(ID_SECRET, _claims())) is None


@pytest.mark.parametrize("over", [
    {"wardrobe_identity_verifier": "assertion", "wardrobe_identity_secret": ""},
    {"wardrobe_identity_verifier": "assertion", "wardrobe_identity_secret": "short"},
    {"wardrobe_identity_verifier": "assertion", "wardrobe_identity_secret": GRANT_SECRET},  # the same secret
    {"wardrobe_identity_verifier": "assertion", "wardrobe_identity_audience": ""},
    {"wardrobe_identity_verifier": "asertion"},
    {"wardrobe_identity_verifier": "no.such.module:factory"},
    {"wardrobe_identity_verifier": "json:no_such_attribute"},
    {"wardrobe_identity_verifier": "json:dumps"},  # a factory that returns no verifier
])
def test_a_misconfigured_verifier_is_no_verifier(over):
    verifier = identity.load_verifier(_settings(**over))
    assert isinstance(verifier, DenyAll) and verifier.configured is False


def test_the_assertion_verifier_loads_from_settings():
    verifier = identity.load_verifier(_settings(wardrobe_identity_verifier="assertion"))
    assert isinstance(verifier, AssertionVerifier) and verifier.issuers == {"nexus-app"}


async def test_identify_accepts_only_an_identity_and_survives_a_broken_verifier():
    alice = Identity("acct-alice", frozenset({"mira"}), True)

    class Sync:
        configured = True

        def verify(self, credential):
            return alice if credential == "ok" else None

    class Async(Sync):
        async def verify(self, credential):
            return alice if credential == "ok" else None

    class Raises(Sync):
        def verify(self, credential):
            raise RuntimeError("the provider is down")

    class Lies(Sync):
        def verify(self, credential):
            return {"subject": "acct-admin", "avatars": ["mira"], "adult": True}  # looks like one

    assert await identity.identify(Sync(), "ok") is alice and await identity.identify(Async(), "ok") is alice
    assert await identity.identify(Sync(), "no") is None
    assert await identity.identify(Raises(), "ok") is None
    assert await identity.identify(Lies(), "ok") is None


def test_authorize_needs_the_avatar_and_an_adult():
    assert identity.authorize(Identity("a", frozenset({"mira"}), True), "mira") == (True, "")
    assert identity.authorize(Identity("a", frozenset({"mira"}), True), "nora") == (False, "not_entitled")
    assert identity.authorize(Identity("a", frozenset({"mira"}), False), "mira") == (
        False, "adult_verification_required")
    assert identity.authorize(Identity("a"), "mira")[0] is False  # the default identity has nothing


# -- revocation --------------------------------------------------------------------------------
async def test_a_capability_or_an_account_can_be_taken_back(tmp_path, settings):
    store = LocalObjectStore(tmp_path / "store", settings)
    _, mine = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-alice")
    _, hers = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-bob")
    _, operator = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=3600)
    for grant in (mine, hers, operator):
        assert not await revocations.revoked(store, settings, grant)
    await revocations.revoke_id(store, mine.id, expires=mine.expires, by="admin", reason="lost phone")
    assert await revocations.revoked(store, settings, mine) and not await revocations.revoked(store, settings, hers)
    await revocations.revoke_subject(store, "acct-bob", by="admin")
    assert await revocations.revoked(store, settings, hers) and await revocations.subject_revoked(
        store, settings, "acct-bob")
    assert not await revocations.revoked(store, settings, operator)
    # A new process over the same storage still refuses them.
    again = LocalObjectStore(tmp_path / "store", settings)
    assert await revocations.revoked(again, settings, mine) and await revocations.revoked(again, settings, hers)
    assert await revocations.restore_subject(store, "acct-bob") and not await revocations.restore_subject(
        store, "acct-bob")
    assert not await revocations.revoked(store, settings, hers)
    # The environment lists survive a disk that does not.
    settings.wardrobe_account_revoked = "acct-zed, acct-bob"
    assert await revocations.revoked(store, settings, hers)
    settings.wardrobe_grant_revoked = operator.id
    assert await revocations.revoked(store, settings, operator)


async def test_an_expired_revocation_is_dropped_and_a_live_one_kept(tmp_path, settings):
    store = LocalObjectStore(tmp_path / "store", settings)
    await revocations.revoke_id(store, "old", expires=int(time.time()) - 5, by="admin")
    await revocations.revoke_id(store, "live", expires=int(time.time()) + 500, by="admin")
    data = await revocations.load(store, fresh=True)
    assert set(data["ids"]) == {"live"}


async def test_revocations_asked_for_at_once_are_all_kept(tmp_path, settings):
    """Review finding on AC1: each change read the whole list, then wrote the whole list, with
    nothing between them. Ten at once each read the same list and all but the last writes were
    lost: an account the operator had been told was revoked kept its access."""
    import asyncio

    store = LocalObjectStore(tmp_path / "store", settings)
    subjects = [f"acct-{n}" for n in range(10)]
    await asyncio.gather(*(revocations.revoke_subject(store, subject, by="admin") for subject in subjects))
    assert set((await revocations.load(store, fresh=True))["subjects"]) == set(subjects)
    # Mixed: ids, another account and a restoration, together.
    soon = int(time.time()) + 500
    await asyncio.gather(
        *(revocations.revoke_id(store, f"grant-{n}", expires=soon, by="admin") for n in range(10)),
        revocations.revoke_subject(store, "acct-late", by="admin"),
        revocations.restore_subject(store, "acct-0"))
    data = await revocations.load(store, fresh=True)
    assert set(data["ids"]) == {f"grant-{n}" for n in range(10)}
    assert set(data["subjects"]) == (set(subjects) - {"acct-0"}) | {"acct-late"}
    # After a restart: a new process over the same disk, nothing kept in memory.
    again = LocalObjectStore(tmp_path / "store", settings)
    _, kept = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-7")
    _, back = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-0")
    assert await revocations.revoked(again, settings, kept) and not await revocations.revoked(again, settings, back)
    assert (await revocations.load(again, fresh=True)) == data


async def test_a_hundred_changes_at_once_lose_nothing(tmp_path, settings):
    """The stress case: accounts and tokens revoked and accounts restored, all at once."""
    import asyncio

    store = LocalObjectStore(tmp_path / "store", settings)
    soon = int(time.time()) + 500
    await asyncio.gather(*(revocations.revoke_subject(store, f"old-{n}", by="admin") for n in range(20)))
    await asyncio.gather(
        *(revocations.revoke_subject(store, f"acct-{n}", by="admin") for n in range(40)),
        *(revocations.revoke_id(store, f"grant-{n}", expires=soon, by="admin") for n in range(40)),
        *(revocations.restore_subject(store, f"old-{n}") for n in range(20)))
    data = await revocations.load(LocalObjectStore(tmp_path / "store", settings), fresh=True)
    assert set(data["subjects"]) == {f"acct-{n}" for n in range(40)}
    assert set(data["ids"]) == {f"grant-{n}" for n in range(40)}


class _Bucket:
    """An S3 bucket in memory that honours ``If-Match`` / ``If-None-Match`` as S3 does, shared by
    every client made while it is installed: two ``S3ObjectStore`` objects are two processes."""

    class Refused(Exception):
        def __init__(self, code, http):
            super().__init__(code)
            self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": http}}

    def __init__(self):
        import threading

        self.objects: dict[str, tuple[bytes, str]] = {}
        self.refused = 0
        self.guard = threading.Lock()
        self.serial = 0

    def client(self, *args, **kwargs):
        return self

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.Refused("404", 404)
        return {}

    def get_object(self, Bucket, Key):
        import io

        with self.guard:
            if Key not in self.objects:
                raise self.Refused("NoSuchKey", 404)
            body, etag = self.objects[Key]
        time.sleep(0.002)  # a network: other writers get in between a read and its write
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        time.sleep(0.002)
        with self.guard:
            held = self.objects.get(Key)
            if (IfNoneMatch == "*" and held is not None) or (IfMatch is not None and (held or (0, 0))[1] != IfMatch):
                self.refused += 1
                raise self.Refused("PreconditionFailed", 412)
            self.serial += 1
            self.objects[Key] = (bytes(Body), f'"etag-{self.serial}"')
        return {}


@pytest.fixture
def bucket(monkeypatch):
    import sys
    import types

    held = _Bucket()
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=held.client))
    return held


def _s3(settings):
    from wardrobe.storage.object_store import S3ObjectStore

    return S3ObjectStore(settings.model_copy(update={"s3_bucket": "forge"}))


async def test_two_processes_on_s3_revoking_at_once_keep_both(settings, bucket):
    """No disk, so no lock file: each write names the version it read, a refused write is done
    again on what the other process wrote. Three stores are three Forge processes on one bucket."""
    import asyncio

    stores = [_s3(settings) for _ in range(3)]
    soon = int(time.time()) + 500
    await asyncio.gather(
        *(revocations.revoke_subject(stores[n % 3], f"acct-{n}", by="admin") for n in range(12)),
        *(revocations.revoke_id(stores[n % 3], f"grant-{n}", expires=soon, by="admin") for n in range(12)))
    assert bucket.refused > 0  # the race happened, and was caught by the condition
    data = await revocations.load(_s3(settings), fresh=True)  # a fourth process, after the fact
    assert set(data["subjects"]) == {f"acct-{n}" for n in range(12)}
    assert set(data["ids"]) == {f"grant-{n}" for n in range(12)}
    assert await revocations.restore_subject(stores[0], "acct-3")
    assert not await revocations.restore_subject(stores[1], "acct-3")
    assert "acct-3" not in (await revocations.load(stores[2], fresh=True))["subjects"]


async def test_a_change_that_can_never_be_written_is_an_error_not_an_acknowledgement(settings, bucket, monkeypatch):
    """If the list keeps changing under a change, the operator is told it was not written."""
    store = _s3(settings)
    await revocations.revoke_subject(store, "acct-first", by="admin")

    async def always_changed(key, data, version, *, content_type=None):
        return False

    monkeypatch.setattr(store, "put_if_unchanged", always_changed)
    with pytest.raises(ValueError, match="kept changing"):
        await revocations.revoke_subject(store, "acct-second", by="admin")
    assert set((await revocations.load(_s3(settings), fresh=True))["subjects"]) == {"acct-first"}


def _revoke_from_another_process(root: str, subject: str) -> None:
    import asyncio

    from wardrobe.config import Settings

    store = LocalObjectStore(root, Settings())
    asyncio.run(revocations.revoke_subject(store, subject, by="admin"))


def test_revocations_from_several_processes_are_all_kept(tmp_path):
    """Two Forge processes over one disk (two workers, or the API and a maintenance script)."""
    import asyncio
    import multiprocessing

    from wardrobe.config import Settings

    root = str(tmp_path / "store")
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_revoke_from_another_process, args=(root, f"acct-{n}")) for n in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert [worker.exitcode for worker in workers] == [0] * 6
    data = asyncio.run(revocations.load(LocalObjectStore(root, Settings()), fresh=True))
    assert set(data["subjects"]) == {f"acct-{n}" for n in range(6)}


async def test_an_unreadable_revocation_list_refuses_every_grant(tmp_path, settings):
    """Fail closed: if nobody can tell whether a token was taken back, it was."""
    store = LocalObjectStore(tmp_path / "store", settings)
    _, grant = grants.mint(GRANT_SECRET, slugs=["mira"], ttl_s=300, subject="acct-alice")
    await store.put(revocations.KEY, b"{ not json")
    assert await revocations.load(store, fresh=True) is None
    assert await revocations.revoked(store, settings, grant)
    assert await revocations.subject_revoked(store, settings, "acct-alice")
    with pytest.raises(ValueError):
        await revocations.revoke_subject(store, "acct-bob", by="admin")
