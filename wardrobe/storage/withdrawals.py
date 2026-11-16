"""WD1. Withdrawal receipts: what makes "withdrawn" a stored fact instead of an absence.

Before this, withdrawing an imported body state meant deleting things: its list item, its
files, its private marker. An absence cannot be told from "not here yet", so everything that
fills gaps put the look back:

* **The dataset store.** ``HfDatasetObjectStore.delete`` removed the local copy only. ``exists``
  then answered from the dataset's listing and ``get`` downloaded the file again: on a Space
  the withdrawal reported its files as remaining for ever, and the look was served the whole time.
* **A restart with fresh local storage.** ``read_list`` merges this store's list with the
  dataset's (RU2). The local list was gone with the disk, the dataset's still named the look,
  and the look was back in her wardrobe with its VRM one download away.
* **Publishing.** ``dataset_publish.publish`` merges the local list with the dataset's so a
  publish never drops a look (PB7). A withdrawn look is a look the local list dropped: the
  merge restored it from the dataset's stale copy on the next batch.

A receipt (``withdrawn/<lookId>.json``) is written **before** anything is deleted and is never
deleted itself. While its state is ``pending`` or ``withdrawn`` the look is not listed
(``prebuilt.read_list``), not served (``/v1/assets``), not published and not merged back
(``dataset_publish.publish``), from whichever copy names it. It travels to the dataset in the
same commit that deletes the look's files there, so a new process over empty storage reads the
receipt before it can read the look.

States, and the only moves between them:

    (none) --withdraw--> pending --every file confirmed gone--> withdrawn
    pending  --withdraw again / resume at startup--> pending | withdrawn
    withdrawn --the operator imports the same bytes again--> restored --withdraw--> pending

``restored`` is the operator's own act (``prebuilt.register_import``), never a merge's. An
unreadable receipt counts as ``pending``: a look is never served on a receipt nobody can read.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

PREFIX = "withdrawn"
#: A receipt's storage key. One level, like a prebuilt entry: never inside the look's folder,
#: which is what a withdrawal deletes.
RECEIPT = re.compile(r"^withdrawn/[^/]+\.json$")
SCHEMA_VERSION = 1
PENDING, WITHDRAWN, RESTORED = "pending", "withdrawn", "restored"
#: The receipt is a record, not a log file: the last events are enough to see what happened.
MAX_HISTORY = 40


def receipt_key(look_id: str) -> str:
    return f"{PREFIX}/{look_id}.json"


def look_of_receipt(key: str) -> str | None:
    return key[len(PREFIX) + 1:-len(".json")] if RECEIPT.match(key) else None


def now() -> str:
    return datetime.now(UTC).isoformat()


def parse(data: bytes | str | None) -> dict | None:
    """A receipt from its bytes. Bytes that are not a receipt are a pending one (fail closed)."""
    if data is None:
        return None
    try:
        receipt = json.loads(data)
    except (ValueError, TypeError):
        receipt = None
    if not isinstance(receipt, dict) or receipt.get("state") not in (PENDING, WITHDRAWN, RESTORED):
        return {"schemaVersion": SCHEMA_VERSION, "state": PENDING, "unreadable": True}
    return receipt


def blocks(receipt: dict | None) -> bool:
    """Whether this receipt keeps its look out of every list, every download and every publish."""
    return receipt is not None and receipt.get("state") != RESTORED


def newer(a: dict | None, b: dict | None) -> dict | None:
    """Of two copies of one receipt, the one written last. A blocking one wins a tie."""
    if a is None or b is None:
        return a if b is None else b
    ta, tb = str(a.get("updatedAt") or ""), str(b.get("updatedAt") or "")
    if ta != tb:
        return a if ta > tb else b
    return a if blocks(a) or not blocks(b) else b


async def read(store, look_id: str) -> dict | None:
    """The look's receipt as this store has it, or None. Never raises.

    Not being able to tell is not "no receipt": if the store says the receipt exists and it
    cannot be read, the look is treated as withdrawn until it can.
    """
    key = receipt_key(look_id)
    try:
        if not await store.exists(key):
            return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not check %s: %s", key, exc)
        return None
    try:
        return parse(await store.get(key))
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s exists and could not be read (%s): its look stays withdrawn", key, exc)
        return {"schemaVersion": SCHEMA_VERSION, "state": PENDING, "unreadable": True, "lookId": look_id}


async def is_withdrawn(store, look_id: str) -> bool:
    return blocks(await read(store, look_id))


def event(receipt: dict, name: str, **detail) -> dict:
    """``receipt`` with one more line of history, stamped now. Returns a new dict."""
    stamp = now()
    line = {"at": stamp, "event": name, **{k: v for k, v in detail.items() if v not in (None, [], "")}}
    history = [*receipt.get("history", []), line][-MAX_HISTORY:]
    return {**receipt, "history": history, "updatedAt": stamp}


def begin(previous: dict | None, *, look_id: str, wardrobe_id: str, files: list[str], by: str,
          item: dict | None = None) -> dict:
    """The receipt of a withdrawal that is starting (or starting again). State ``pending``."""
    item = item or {}
    base = previous if previous is not None and not previous.get("unreadable") else {}
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "lookId": look_id,
        "wardrobeId": wardrobe_id,
        "origin": item.get("origin") or base.get("origin") or "operator-import",
        "name": item.get("name") or base.get("name"),
        "wardrobeState": item.get("wardrobeState") or base.get("wardrobeState"),
        "outputSha256": item.get("outputSha256") or base.get("outputSha256"),
        "sourceSha256": item.get("sourceSha256") or base.get("sourceSha256"),
        "files": list(files),
        "requestedAt": now() if base.get("state") in (None, RESTORED) else base.get("requestedAt") or now(),
        "requestedBy": by if base.get("state") in (None, RESTORED) else base.get("requestedBy") or by,
        "completedAt": None,
        "attempts": (0 if base.get("state") in (None, RESTORED) else int(base.get("attempts") or 0)) + 1,
        "remaining": list(files),
        "state": PENDING,
        "history": list(base.get("history", [])),
    }
    return event(receipt, "requested" if receipt["attempts"] == 1 else "retried", by=by)


def failed(receipt: dict, remaining: list[str]) -> dict:
    return event({**receipt, "state": PENDING, "remaining": list(remaining)}, "incomplete",
                 remaining=list(remaining))


def completed(receipt: dict) -> dict:
    done = event({**receipt, "state": WITHDRAWN, "remaining": []}, "withdrawn")
    return {**done, "completedAt": done["updatedAt"]}


def restored(receipt: dict, *, by: str) -> dict:
    return event({**receipt, "state": RESTORED, "remaining": []}, "restored", by=by)


def dumps(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True).encode("utf-8")


__all__ = ["PENDING", "PREFIX", "RECEIPT", "RESTORED", "WITHDRAWN", "begin", "blocks", "completed", "dumps",
           "event", "failed", "is_withdrawn", "look_of_receipt", "newer", "parse", "read", "receipt_key",
           "restored"]
