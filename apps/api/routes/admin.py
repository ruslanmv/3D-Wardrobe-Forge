"""The Studio's account menu: sign in, declare per avatar for this session, sign out.

The rules are in :mod:`apps.api.admin`; this is only their HTTP shape.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import MIN_PASSWORD_LENGTH, AdminDep, AdminError, AdminSessionsDep
from apps.api.dependencies import CatalogDep, OrchestratorDep, SettingsDep, StoreDep
from wardrobe.body_art.custom import MAX_BYTES, CustomArtError, is_custom
from wardrobe.body_art.raster import artwork_png
from wardrobe.body_surface import body_state_import
from wardrobe.pipeline import prebuilt
from wardrobe.policy import grants, revocations

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


class SignIn(BaseModel):
    username: str | None = Field(default=None, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class Declaration(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    depicts_adult: bool = Field(alias="depictsAdult")
    #: The person turning it on confirms they are 18 or older. Required to turn a
    #: declaration on; it is about the viewer and does not replace ``depictsAdult``,
    #: which is about the avatar.
    age_confirmed: bool = Field(default=False, alias="ageConfirmed")


def _raise(error: AdminError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"reason": error.reason, "message": error.message})


def _signed_in(admin) -> None:
    if admin is None:
        raise HTTPException(status_code=401, detail={"reason": "admin_required", "message": "sign in first"})


@router.get("/admin")
def admin_status(admins: AdminSessionsDep, admin: AdminDep) -> dict:
    """Whether this deployment has an admin, and whether this request is signed in."""
    return {
        "enabled": admins.enabled,
        # Why it is off, so the Studio can say what to fix; never anything about the password itself
        # beyond that it is too short, which is already true of every guess a caller could make.
        "unavailable": admins.reason,
        "minPasswordLength": MIN_PASSWORD_LENGTH,
        "signedIn": admin is not None,
        "username": admins.username if admin is not None else None,
        "session": admin.to_dict() if admin is not None else None,
    }


@router.post("/admin/session", status_code=status.HTTP_201_CREATED)
def sign_in(body: SignIn, request: Request, admins: AdminSessionsDep) -> dict:
    client = request.client.host if request.client else "?"
    try:
        token, session = admins.sign_in(body.password, client, username=body.username)
    except AdminError as error:
        raise _raise(error) from None
    return {"token": token, "username": admins.username, **session.to_dict()}


@router.delete("/admin/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(admins: AdminSessionsDep, x_wardrobe_admin: Annotated[str | None, Header()] = None) -> None:
    admins.sign_out(x_wardrobe_admin)


@router.put("/admin/declarations/{slug}")
def declare(
    slug: str, body: Declaration, request: Request, admins: AdminSessionsDep, admin: AdminDep
) -> dict:
    """Declare (or withdraw) that a library avatar depicts an adult, for this session only."""
    _signed_in(admin)
    library = getattr(request.app.state, "library", None)
    avatar = library.get(slug) if library is not None else None
    if avatar is None:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    if body.depicts_adult and not body.age_confirmed:
        raise HTTPException(
            status_code=422,
            detail={"reason": "age_confirmation_required", "message": "confirm you are 18 or older first"},
        )
    admins.declare(admin, avatar.slug, body.depicts_adult)
    return admin.to_dict()


# BA10. The operator's own tattoo artwork. Every route here is an admin session's only: the
# rules (PNG or WebP bytes, limits before pixels, real alpha, re-encoded, private) are in
# wardrobe.body_art.custom, and a job that uses one is made private by the Studio's job route.
CUSTOM_THUMBNAIL = 256


def _custom(orchestrator):
    custom = orchestrator.body_art.custom
    if custom is None:
        detail = {"reason": "unavailable", "message": "no custom tattoos here"}
        raise HTTPException(status_code=404, detail=detail)
    return custom


def _public(meta: dict) -> dict:
    keys = ("id", "name", "aspect", "width", "height", "ink", "createdAt")
    return {**{key: meta[key] for key in keys}, "private": True, "family": "custom"}


@router.get("/admin/body-art")
def list_custom_body_art(orchestrator: OrchestratorDep, admin: AdminDep) -> dict:
    _signed_in(admin)
    return {"designs": [_public(meta) for meta in _custom(orchestrator).list()]}


@router.post("/admin/body-art", status_code=status.HTTP_201_CREATED)
async def upload_custom_body_art(
    orchestrator: OrchestratorDep,
    admin: AdminDep,
    file: UploadFile = File(...),
    name: str = Form(default=""),
) -> dict:
    """A PNG or WebP picture, its alpha the ink. Uploaded bytes only: there is no URL field."""
    _signed_in(admin)
    data = await file.read(MAX_BYTES + 1)
    try:
        meta = _custom(orchestrator).add(data, name, created_at=datetime.now(UTC).isoformat())
    except CustomArtError as error:
        code = 413 if error.reason == "too_large" else 422
        raise HTTPException(status_code=code, detail={"reason": f"body_art_{error.reason}",
                                                       "message": error.message}) from error
    return _public(meta)


@router.get("/admin/body-art/{design_id}.png")
def custom_body_art_thumbnail(design_id: str, orchestrator: OrchestratorDep, admin: AdminDep) -> Response:
    _signed_in(admin)
    custom = _custom(orchestrator)
    if not is_custom(design_id) or custom.entry(design_id) is None:
        raise HTTPException(status_code=404, detail="no such custom tattoo")
    png = artwork_png(custom.artwork(design_id), CUSTOM_THUMBNAIL)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.delete("/admin/body-art/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_body_art(design_id: str, orchestrator: OrchestratorDep, admin: AdminDep) -> None:
    """Its looks keep their tattoo; a new job naming it is refused as an unknown design."""
    _signed_in(admin)
    if not _custom(orchestrator).remove(design_id):
        raise HTTPException(status_code=404, detail="no such custom tattoo")


__all__ = ["router"]


# ----------------------------------------------------------------------
# BI2. Read grants: what the companion app holds instead of this session's token.
# ----------------------------------------------------------------------
class GrantRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slugs: list[str] = Field(min_length=1, max_length=32)
    #: CG8. 0 means no expiry (until revoked): ``grants.NO_EXPIRY_TTL_S``.
    ttl_seconds: int = Field(default=7 * 24 * 3600, alias="ttlSeconds")
    label: str = Field(default="", max_length=80)


@router.post("/admin/grants", status_code=status.HTTP_201_CREATED)
def mint_grant(body: GrantRequest, request: Request, admin: AdminDep, admins: AdminSessionsDep,
               settings: SettingsDep) -> dict:
    """A read-only, expiring grant for these library avatars' private looks (wardrobe.policy.grants)."""
    _signed_in(admin)
    library = getattr(request.app.state, "library", None)
    unknown = [s for s in body.slugs if library is None or library.get(s) is None]
    if unknown:
        raise HTTPException(status_code=404, detail={"reason": "avatar_not_in_library",
                                                     "message": f"not in the library: {', '.join(unknown)}"})
    if not grants.usable(settings.wardrobe_grant_secret):
        raise HTTPException(status_code=409, detail={
            "reason": "grants_unavailable",
            "message": f"set WARDROBE_GRANT_SECRET (at least {grants.MIN_SECRET_LENGTH} characters) "
                       "to mint grants"})
    try:
        ttl = grants.NO_EXPIRY_TTL_S if body.ttl_seconds == 0 else body.ttl_seconds
        token, grant = grants.mint(settings.wardrobe_grant_secret, slugs=body.slugs, ttl_s=ttl,
                                   label=body.label)
    except grants.GrantError as error:
        detail = {"reason": "grant_invalid", "message": str(error)}
        raise HTTPException(status_code=422, detail=detail) from None
    logger.info("read grant %s minted for %s by %s, expires %s", grant.id, sorted(grant.slugs),
                admins.username or "admin", grant.expires)
    return {"token": token, "header": grants.HEADER, **grant.to_dict()}


# ----------------------------------------------------------------------
# BI1. Operator-supplied body states for a library character.
# ----------------------------------------------------------------------
def _library_avatar(request: Request, slug: str):
    library = getattr(request.app.state, "library", None)
    avatar = library.get(slug) if library is not None else None
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    return avatar


@router.get("/admin/library/{slug}/body-states")
async def list_body_states(slug: str, request: Request, admin: AdminDep, store: StoreDep) -> dict:
    """Her imported body states, with what each import's check said."""
    _signed_in(admin)
    _library_avatar(request, slug)
    listed = await prebuilt.read_list(store, slug)
    items = [item for item in listed.get("looks", []) if item.get("origin") == "operator-import"]
    return {"slug": slug, "count": len(items), "looks": items}


@router.post("/admin/library/{slug}/body-states", status_code=status.HTTP_201_CREATED)
async def import_body_state(
    slug: str,
    request: Request,
    admin: AdminDep,
    store: StoreDep,
    settings: SettingsDep,
    admins: AdminSessionsDep,
    catalog: CatalogDep,
    file: UploadFile = File(...),
    state: str = Form(...),
    source_sha256: str = Form(..., alias="sourceSha256"),
    sha256: str = Form(default=""),
    name: str = Form(default="", max_length=80),
    licence: str = Form(..., min_length=3, max_length=500),
    rights_attested: bool = Form(..., alias="rightsAttested"),
    garments: str = Form(default="", max_length=500),
) -> dict:
    """Import an authorized body-state VRM of a library character, bound to her pinned SHA-256.

    Uploaded bytes only (there is no URL field). ``licence`` says under what terms the operator
    holds this file and ``rightsAttested`` that they hold them; both are recorded with the import,
    neither is a permission. Permission is ``body_state_import.check``: the same eligibility
    contract as body-bare-v1, run for her file and for this one, plus the structural, rig and
    identity checks. Refused: 422 with every check's answer. Accepted: stored private, listed in
    her wardrobe, readable by an admin session or a read grant for her.
    """
    _signed_in(admin)
    if not rights_attested:
        detail = {"reason": "rights_not_attested", "message": "attest that you hold the rights to this file"}
        raise HTTPException(status_code=422, detail=detail)
    avatar = _library_avatar(request, slug)
    data = await file.read(body_state_import.MAX_BYTES + 1)
    original = avatar.path.read_bytes()
    depicts_adult = bool(avatar.depicts_adult or slug in admin.declared)
    verdict = body_state_import.check(
        data, original, state=state, source_sha256=source_sha256, declared_sha256=sha256 or None,
        operator_enabled=settings.wardrobe_adult_body_surface, depicts_adult=depicts_adult,
        review_root=settings.body_surface_root_path, reference_root=settings.wardrobe_calibration_root)
    if not verdict.accepted:
        logger.info("body-state import for %s refused: %s", slug, verdict.reason)
        raise HTTPException(status_code=413 if verdict.reason == "too-large" else 422,
                            detail={"reason": f"body_state_{verdict.reason.replace('-', '_')}",
                                    "message": verdict.message, "verdict": verdict.to_dict()})
    # What it is made of: the file's own garment tags when Forge built it; otherwise the operator
    # may name catalogue templates (comma separated), each one checked to exist. Unknown is
    # allowed and stays unknown: the app then never offers it as a step of undressing.
    worn = verdict.checks.get("garments", {}).get("fromFile") or []
    if not worn and garments.strip():
        named = [g.strip() for g in garments.split(",") if g.strip()]
        unknown = [g for g in named if catalog is None or catalog.get(g) is None]
        if unknown:
            detail = {"reason": "body_state_garments_unknown",
                      "message": f"not in the catalogue: {', '.join(unknown)}"}
            raise HTTPException(status_code=422, detail=detail)
        worn = named
    look_id = prebuilt.import_look_id(verdict.sha256)
    item = await prebuilt.register_import(
        store, slug, data, verdict=verdict.to_dict(), state=state,
        name=name.strip() or f"{avatar.name} ({state})", source_sha256=avatar.sha256,
        output_sha256=verdict.sha256, imported_by=admins.username or "admin",
        provenance={"licence": licence, "rightsAttested": True, "fileName": file.filename or None,
                    "uploadedBytes": len(data)},
        vrm_url=settings.artifact_url(f"looks/{look_id}/look.vrm"), garments=worn)
    logger.info("body-state import %s (%s) registered for %s", look_id, state, slug)
    return {"look": item, "verdict": verdict.to_dict()}


@router.delete("/admin/library/{slug}/body-states/{look_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_body_state(slug: str, look_id: str, request: Request, admin: AdminDep,
                              store: StoreDep, admins: AdminSessionsDep) -> None:
    """Withdraw an imported body state. 204: withdrawn (also when it already was: repeating is
    safe). 503: out of her list and blocked, but some files remain; repeat to finish. 404: she
    has no such import and never withdrew one. The receipt is at ``…/withdrawals``."""
    _signed_in(admin)
    _library_avatar(request, slug)
    result = await prebuilt.withdraw_import(store, slug, look_id, withdrawn_by=admins.username or "admin")
    if result is None:
        raise HTTPException(status_code=404, detail="no such imported body state")
    if not result["withdrawn"]:
        # Out of her list and no longer served to anyone (WD1: the receipt blocks it), but some
        # files could not be deleted. Call again to finish; it is safe to repeat, and a restart
        # resumes it too.
        raise HTTPException(status_code=503, detail={
            "reason": "body_state_withdraw_incomplete", "remaining": result["remaining"],
            "message": "some files could not be deleted; the look is blocked. Retry the withdrawal."})
    logger.info("body-state import %s withdrawn from %s%s", look_id, slug,
                " (already was)" if result["repeated"] else "")


@router.get("/admin/library/{slug}/withdrawals")
async def list_withdrawals(slug: str, request: Request, admin: AdminDep, store: StoreDep) -> dict:
    """WD1. Her withdrawal receipts: what was withdrawn, by whom, when, and what (if anything)
    still remains to delete. A receipt is kept for good; ``restored`` means the operator
    imported the same file again afterwards."""
    _signed_in(admin)
    _library_avatar(request, slug)
    receipts = await prebuilt.list_withdrawals(store, slug)
    return {"slug": slug, "count": len(receipts), "withdrawals": receipts}


# ----------------------------------------------------------------------
# AC1. Taking access back: one capability or grant by id, or an account.
# ----------------------------------------------------------------------
class Revocation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    #: A token to revoke (its ``jti``), by presenting the token itself, so its expiry is known
    #: and an id is never revoked on a guess.
    token: str | None = Field(default=None, max_length=4096)
    #: An account to revoke: every capability it holds, and every one it asks for, until restored.
    subject: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str = Field(default="", max_length=200)


@router.get("/admin/access/revocations")
async def list_revocations(admin: AdminDep, store: StoreDep) -> dict:
    _signed_in(admin)
    data = await revocations.load(store, fresh=True)
    if data is None:
        raise HTTPException(status_code=500, detail={"reason": "revocations_unreadable",
                                                     "message": "the revocation list cannot be read; "
                                                                "every grant is refused until it can"})
    return {"ids": data["ids"], "subjects": data["subjects"]}


@router.post("/admin/access/revocations", status_code=status.HTTP_201_CREATED)
async def revoke_access(body: Revocation, admin: AdminDep, admins: AdminSessionsDep, store: StoreDep,
                        settings: SettingsDep) -> dict:
    """Revoke a token (operator grant or account capability) or an account. Effective at once here,
    within ``revocations.CACHE_S`` seconds in another process on the same storage."""
    _signed_in(admin)
    if (body.token is None) == (body.subject is None):
        raise HTTPException(status_code=422, detail={"reason": "revocation_invalid",
                                                     "message": "name a token or a subject, one of them"})
    by = admins.username or "admin"
    try:
        if body.subject is not None:
            entry = await revocations.revoke_subject(store, body.subject, by=by, reason=body.reason)
            logger.info("account %s revoked by %s", body.subject, by)
            return {"subject": body.subject, **entry}
        grant = grants.verify(settings.wardrobe_grant_secret, body.token)
        if grant is None:
            raise HTTPException(status_code=422, detail={"reason": "grant_invalid",
                                                         "message": "not a live grant of this deployment"})
        entry = await revocations.revoke_id(store, grant.id, expires=grant.expires, by=by, reason=body.reason)
    except ValueError as error:
        raise HTTPException(status_code=500, detail={"reason": "revocations_unreadable",
                                                     "message": str(error)}) from None
    logger.info("grant %s revoked by %s", grant.id, by)
    return {"id": grant.id, **entry}


@router.delete("/admin/access/revocations/subjects/{subject:path}", status_code=status.HTTP_204_NO_CONTENT)
async def restore_access(subject: str, admin: AdminDep, store: StoreDep) -> None:
    """Give an account its access back: it may be issued capabilities again."""
    _signed_in(admin)
    try:
        found = await revocations.restore_subject(store, subject)
    except ValueError as error:
        raise HTTPException(status_code=500, detail={"reason": "revocations_unreadable",
                                                     "message": str(error)}) from None
    if not found:
        raise HTTPException(status_code=404, detail="that account is not revoked")
