"""CG4. Character review in the Studio: the exact file on screen, and a person's own finding recorded.

Before this, recording a design review meant a terminal: build a packet, then run
``tools/body_surface/gates.py record`` with a 64-character hash typed by hand. Nobody did, and the
registry stayed empty. The review is a person's job, and these routes make it one a person can do
in the Studio without making it any easier to fake:

* **Who.** Only an admin session (``WARDROBE_ADMIN_PASSWORD``). A guest gets 401, as for every
  other operator route. The reviewer's name is typed by the person and is required; the session's
  username is not substituted for it.
* **What.** The finding is the person's: ``outcome`` has no default and must be one of
  ``REVIEW_OUTCOMES``. Nothing here proposes, pre-selects or infers one — not from the operator's
  declaration, not from the file's terms, not from the viewer's own adult confirmation.
* **Which bytes.** The request names the SHA-256 the reviewer was shown. It must equal the library
  pin, and ``record_review`` hashes the file on disk again, so a review can only land on the bytes
  the Studio loaded and hashed in the browser.
* **Once.** ``record_review`` refuses a second finding for the same bytes; a new finding is for a
  new file. ``pending`` (nobody has looked) is never written: it is what an absent entry means.

The registry is a file (``adult-design-reviews.json``). On a deployment whose disk does not
persist, a finding written here lasts until restart: the response says to commit it, and the
Studio shows that.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import AdminDep
from apps.api.dependencies import SettingsDep, StoreDep
from wardrobe.body_surface.character_gates import REVIEW_OUTCOMES, measure_body_state, record_review, status
from wardrobe.pipeline import prebuilt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["review"])

REGISTRY_FILE = "adult-design-reviews.json"

#: Body measurements by exact SHA-256. They depend on the bytes alone, and one takes seconds.
_BODY_CACHE: dict[str, dict] = {}


class Finding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    outcome: str
    reviewer: str = Field(min_length=1, max_length=120)
    evidence: str = Field(min_length=1, max_length=2000)
    #: The person states they looked at the rendered model themselves, from every side.
    examined: bool = False


def _signed_in(admin) -> None:
    if admin is None:
        raise HTTPException(status_code=401, detail={"reason": "admin_required", "message": "sign in first"})


async def _avatars(request: Request, store):
    from apps.api.routes.studio import _refresh_library

    return await _refresh_library(request, store)


async def _body_state_files(store, slug: str) -> int:
    """Accepted bare body-state imports for her (operator imports; withdrawn ones are not listed)."""
    try:
        listed = await prebuilt.read_list(store, slug)
    except Exception as exc:  # noqa: BLE001 - an unreadable list means none, said in the log
        logger.warning("review: body-state list for %s unreadable: %s", slug, exc)
        return 0
    return sum(1 for item in listed.get("looks", [])
               # register_import lists the state as ``wardrobeState`` (BL1's field); ``state`` is
               # the import record's own name for it, kept for any list written that way.
               if item.get("origin") == "operator-import"
               and (item.get("wardrobeState") or item.get("state")) == "bare")


def _body(avatar) -> dict:
    cached = _BODY_CACHE.get(avatar.sha256)
    if cached is None:
        try:
            cached = measure_body_state(avatar.path)
        except Exception as exc:  # noqa: BLE001 - fail soft: report not measured, never complete
            logger.warning("review: body of %s not measured: %s", avatar.slug, exc)
            return {}
        _BODY_CACHE[avatar.sha256] = cached
    return cached


async def _row(avatar, settings, store, declared: set[str]) -> dict:
    body = dict(await run_in_threadpool(_body, avatar))
    body["bodyStateFiles"] = await _body_state_files(store, avatar.slug)
    depicts_adult = bool(avatar.depicts_adult or avatar.slug in declared)
    # A Studio import whose terms were silent was accepted on the operator's attestation; that is
    # the library's record of the right to modify, as the dressing pipeline already reads it.
    conditions = avatar.granted_conditions or (
        {"modification": "allow"} if avatar.user_attests_modification_allowed else None)
    row = await run_in_threadpool(
        lambda: status(avatar.path, slug=avatar.slug, depicts_adult=depicts_adult,
                       pinned_sha256=avatar.sha256, settings=settings, body=body,
                       library_conditions=conditions))
    row.pop("file", None)  # a server path is nobody's business
    row["name"] = avatar.name
    row["collection"] = avatar.collection
    row["avatarUrl"] = f"/v1/library/{avatar.slug}/avatar.vrm"
    return row


@router.get("/admin/reviews")
async def list_reviews(request: Request, admin: AdminDep, settings: SettingsDep, store: StoreDep) -> dict:
    """Every available library character: review state, licence, body and status, per exact file."""
    _signed_in(admin)
    library = await _avatars(request, store)
    rows = [await _row(a, settings, store, admin.declared) for a in library.available()]
    missing = [a.slug for a in library.avatars if not a.available]
    return {"outcomes": list(REVIEW_OUTCOMES), "characters": rows, "notOnDisk": missing}


@router.post("/admin/reviews/{slug}", status_code=201)
async def record(slug: str, body: Finding, request: Request, admin: AdminDep, settings: SettingsDep,
                 store: StoreDep) -> dict:
    """Record one person's finding for the exact file the Studio showed them."""
    _signed_in(admin)
    library = await _avatars(request, store)
    avatar = library.get(slug)
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    if not body.examined:
        raise HTTPException(status_code=422, detail={
            "reason": "not_examined", "message": "confirm you looked at the rendered model yourself"})
    if body.outcome not in REVIEW_OUTCOMES:
        raise HTTPException(status_code=422, detail={
            "reason": "outcome_invalid", "message": f"outcome must be one of {', '.join(REVIEW_OUTCOMES)}"})
    if body.sha256 != avatar.sha256:
        raise HTTPException(status_code=409, detail={
            "reason": "not_this_file", "message": "that SHA-256 is not the file this character is pinned to"})
    registry = settings.body_surface_root_path / REGISTRY_FILE
    date = datetime.now(UTC).date().isoformat()
    try:
        entry = await run_in_threadpool(
            record_review, registry, file=avatar.path, sha256=body.sha256, outcome=body.outcome,
            reviewer=body.reviewer, evidence=f"{body.evidence.strip()} [recorded in Studio]", date=date)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"reason": "refused", "message": str(exc)}) from None
    actual = hashlib.sha256(avatar.path.read_bytes()).hexdigest()
    logger.info("review recorded for %s (%s): %s by %s", slug, actual[:12], body.outcome, body.reviewer)
    row = await _row(avatar, settings, store, admin.declared)
    return {"entry": entry, "character": row,
            "persist": f"commit {REGISTRY_FILE} (assets/body_surface/) under the reviewer's name; "
                       "a disk that does not persist loses it at restart"}


__all__ = ["router"]
