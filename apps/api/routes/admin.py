"""The Studio's account menu: sign in, declare per avatar for this session, sign out.

The rules are in :mod:`apps.api.admin`; this is only their HTTP shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import MIN_PASSWORD_LENGTH, AdminDep, AdminError, AdminSessionsDep
from apps.api.dependencies import OrchestratorDep
from wardrobe.body_art.custom import MAX_BYTES, CustomArtError, is_custom
from wardrobe.body_art.raster import artwork_png

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
