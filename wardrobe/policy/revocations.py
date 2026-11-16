"""AC1. Revoking a capability, or an account, while tokens are still stateless.

A grant is an HMAC over its own claims: nothing is looked up to verify it, which is why it
survives a restart and why it cannot be taken back by forgetting it. Before AC1 the only ways
were an environment variable of grant ids (``WARDROBE_GRANT_REVOKED``, a redeploy) and rotating
the secret (everyone, at once). An account capability lives minutes, but "this account must
lose access now" cannot wait minutes or a redeploy.

The list is one small object in the store (``access/revocations.json``), written by an admin
session (``/v1/admin/access/revocations``):

* **ids** — one capability or grant, until its own expiry passes (then the entry is dropped:
  the token is dead anyway).
* **subjects** — an account. Every capability issued to it is refused, and no new one is
  issued, until the operator restores it.

``WARDROBE_GRANT_REVOKED`` (ids) and ``WARDROBE_ACCOUNT_REVOKED`` (subjects) are checked as
well, and are what survives a disk that does not: the store's copy is local storage, kept off
the prebuilt dataset on purpose (account ids are not catalogue data).

Read on every request that carries a grant, so it is cached per store for ``CACHE_S`` seconds;
a write in this process is seen at once. Another process sees it within ``CACHE_S``. If the
list exists and cannot be read, every grant is refused until it can: fail closed.
"""

from __future__ import annotations

import json
import logging
import time
import weakref
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

KEY = "access/revocations.json"
PREFIX = "access"
SCHEMA_VERSION = 1
CACHE_S = 10.0
MAX_ENTRIES = 5000

_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _empty() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "ids": {}, "subjects": {}}


def _split(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


async def load(store, *, fresh: bool = False) -> dict | None:
    """The list, or None when it exists and cannot be read (the caller then refuses everything)."""
    cached = _cache.get(store)
    if cached is not None and not fresh and time.monotonic() - cached[0] < CACHE_S:
        return cached[1]
    try:
        if not await store.exists(KEY):
            data: dict | None = _empty()
        else:
            raw = json.loads(await store.get(KEY))
            if not isinstance(raw, dict) or not isinstance(raw.get("ids"), dict) \
                    or not isinstance(raw.get("subjects"), dict):
                raise ValueError("not a revocation list")
            data = raw
    except Exception as exc:  # noqa: BLE001
        logger.error("the revocation list could not be read (%s); every grant is refused until it can", exc)
        data = None
    _cache[store] = (time.monotonic(), data)
    return data


async def _save(store, data: dict) -> None:
    current = int(time.time())
    # An id whose token has expired needs no entry; a subject stays until restored.
    data["ids"] = {key: entry for key, entry in data["ids"].items()
                   if int(entry.get("expires") or 0) > current}
    if len(data["ids"]) + len(data["subjects"]) > MAX_ENTRIES:
        raise ValueError("the revocation list is full; restore accounts or rotate the grant secret")
    await store.put(KEY, json.dumps(data, sort_keys=True).encode("utf-8"), content_type="application/json")
    _cache[store] = (time.monotonic(), data)


async def _current(store) -> dict:
    data = await load(store, fresh=True)
    if data is None:
        raise ValueError("the revocation list is unreadable; fix or remove access/revocations.json")
    return {"schemaVersion": SCHEMA_VERSION, "ids": dict(data["ids"]), "subjects": dict(data["subjects"])}


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


async def revoke_id(store, grant_id: str, *, expires: int, by: str, reason: str = "") -> dict:
    data = await _current(store)
    entry = {"at": _stamp(), "by": by, "reason": reason[:200], "expires": int(expires)}
    data["ids"][grant_id] = entry
    await _save(store, data)  # drops entries whose token has already expired, this one included
    return entry


async def revoke_subject(store, subject: str, *, by: str, reason: str = "") -> dict:
    data = await _current(store)
    data["subjects"][subject] = {"at": _stamp(), "by": by, "reason": reason[:200]}
    await _save(store, data)
    return data["subjects"][subject]


async def restore_subject(store, subject: str) -> bool:
    data = await _current(store)
    if subject not in data["subjects"]:
        return False
    del data["subjects"][subject]
    await _save(store, data)
    return True


async def subject_revoked(store, settings, subject: str | None) -> bool:
    if not subject:
        return False
    if subject in _split(getattr(settings, "wardrobe_account_revoked", "")):
        return True
    data = await load(store)
    return data is None or subject in data["subjects"]


async def revoked(store, settings, grant) -> bool:
    """Whether this verified grant has been taken back: by id, by account, or because nobody can tell."""
    if grant.id in _split(getattr(settings, "wardrobe_grant_revoked", "")):
        return True
    if grant.subject and grant.subject in _split(getattr(settings, "wardrobe_account_revoked", "")):
        return True
    data = await load(store)
    if data is None:
        return True
    return grant.id in data["ids"] or bool(grant.subject and grant.subject in data["subjects"])


__all__ = ["KEY", "PREFIX", "load", "restore_subject", "revoke_id", "revoke_subject", "revoked",
           "subject_revoked"]
