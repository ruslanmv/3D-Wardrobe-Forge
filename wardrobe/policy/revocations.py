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

A change is read-the-list, edit, write-the-list, and it is made by one writer at a time
(``_exclusive``). Without that, two changes that overlapped each read the same list and the
second write dropped the first: ten revocations asked for together left one or two on disk,
each of them acknowledged to the operator. In one process the turn is an asyncio lock; between
processes over one disk (several workers, the API and a script) it is a lock file beside the
list. An S3 store has no disk to put a lock file on: there each write is conditional on the
version that was read (``If-Match``), and a refused write is redone on the list as the other
process left it (``_change``; docs/ACCOUNT_ACCESS.md says which services honour that).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import weakref
from datetime import UTC, datetime

try:  # POSIX. Without it (Windows) the turn is per process.
    import fcntl
except ImportError:  # pragma: no cover - platform
    fcntl = None

logger = logging.getLogger(__name__)

KEY = "access/revocations.json"
#: Held, never read: its only content is who has the turn. ``access/`` is never served.
LOCK_KEY = "access/revocations.lock"
PREFIX = "access"
SCHEMA_VERSION = 1
CACHE_S = 10.0
MAX_ENTRIES = 5000
#: How often a change is redone when a conditional write finds the list changed under it.
ATTEMPTS = 25

_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
#: store -> (event loop, lock). A lock belongs to the loop that first waited on it.
_turns: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _lock_file(store):
    """Take the lock file of a store that lives on a disk (blocking: call in a thread)."""
    local_path = getattr(store, "local_path", None)
    if fcntl is None or local_path is None:
        return None
    path = local_path(LOCK_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")  # noqa: SIM115 - held until the change is written
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
    except BaseException:
        handle.close()
        raise
    return handle


@contextlib.asynccontextmanager
async def _exclusive(store):
    """One change to the list at a time: in this process, and across processes on one disk."""
    loop = asyncio.get_running_loop()
    turn = _turns.get(store)
    if turn is None or turn[0] is not loop:
        turn = (loop, asyncio.Lock())
        _turns[store] = turn
    async with turn[1]:
        handle = await asyncio.to_thread(_lock_file, store)
        try:
            yield
        finally:
            if handle is not None:
                handle.close()  # closing releases the lock


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
            data = _valid(json.loads(await store.get(KEY)))
    except Exception as exc:  # noqa: BLE001
        logger.error("the revocation list could not be read (%s); every grant is refused until it can", exc)
        data = None
    _cache[store] = (time.monotonic(), data)
    return data


def _valid(raw) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("ids"), dict) \
            or not isinstance(raw.get("subjects"), dict):
        raise ValueError("not a revocation list")
    return raw


def _payload(data: dict) -> bytes:
    current = int(time.time())
    # An id whose token has expired needs no entry; a subject stays until restored.
    data["ids"] = {key: entry for key, entry in data["ids"].items()
                   if int(entry.get("expires") or 0) > current}
    if len(data["ids"]) + len(data["subjects"]) > MAX_ENTRIES:
        raise ValueError("the revocation list is full; restore accounts or rotate the grant secret")
    return json.dumps(data, sort_keys=True).encode("utf-8")


async def _current(store) -> dict:
    data = await load(store, fresh=True)
    if data is None:
        raise ValueError("the revocation list is unreadable; fix or remove access/revocations.json")
    return {"schemaVersion": SCHEMA_VERSION, "ids": dict(data["ids"]), "subjects": dict(data["subjects"])}


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


async def _change(store, edit):
    """Read the list, let ``edit(data)`` change it, write it: as one step no other writer splits.

    ``edit`` returns ``(result, changed)``. On a disk the step is held by ``_exclusive``. On a
    store that writes on condition (S3) the write names the version that was read, and when
    somebody else wrote in between it is refused and the whole step is done again on the list
    as it is now: the other writer's change is kept, and so is this one.
    """
    async with _exclusive(store):
        for _ in range(ATTEMPTS):
            versioned = await store.read_versioned(KEY)
            if versioned is None:
                data = await _current(store)
            else:
                try:
                    data = _valid(json.loads(versioned[0])) if versioned[0] is not None else _empty()
                except ValueError:
                    raise ValueError(
                        "the revocation list is unreadable; fix or remove access/revocations.json") from None
            result, changed = edit(data)
            if not changed:
                return result
            payload = _payload(data)
            kind = "application/json"
            if versioned is None:
                await store.put(KEY, payload, content_type=kind)
            elif not await store.put_if_unchanged(KEY, payload, versioned[1], content_type=kind):
                continue  # another process wrote first: read what it wrote, and edit that
            _cache[store] = (time.monotonic(), data)
            return result
        raise ValueError("the revocation list kept changing under this change; nothing was written")


async def revoke_id(store, grant_id: str, *, expires: int, by: str, reason: str = "") -> dict:
    entry = {"at": _stamp(), "by": by, "reason": reason[:200], "expires": int(expires)}

    def edit(data: dict):
        data["ids"][grant_id] = entry
        return entry, True  # the write drops entries whose token has expired, this one included

    return await _change(store, edit)


async def revoke_subject(store, subject: str, *, by: str, reason: str = "") -> dict:
    entry = {"at": _stamp(), "by": by, "reason": reason[:200]}

    def edit(data: dict):
        data["subjects"][subject] = entry
        return entry, True

    return await _change(store, edit)


async def restore_subject(store, subject: str) -> bool:
    def edit(data: dict):
        if subject not in data["subjects"]:
            return False, False
        del data["subjects"][subject]
        return True, True

    return await _change(store, edit)


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
