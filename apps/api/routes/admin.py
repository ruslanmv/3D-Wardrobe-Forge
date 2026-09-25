"""The Studio's account menu: sign in, declare per avatar for this session, sign out.

The rules are in :mod:`apps.api.admin`; this is only their HTTP shape.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import AdminDep, AdminError, AdminSessionsDep

router = APIRouter(tags=["admin"])


class SignIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class Declaration(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    depicts_adult: bool = Field(alias="depictsAdult")


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
        "signedIn": admin is not None,
        "session": admin.to_dict() if admin is not None else None,
    }


@router.post("/admin/session", status_code=status.HTTP_201_CREATED)
def sign_in(body: SignIn, request: Request, admins: AdminSessionsDep) -> dict:
    client = request.client.host if request.client else "?"
    try:
        token, session = admins.sign_in(body.password, client)
    except AdminError as error:
        raise _raise(error) from None
    return {"token": token, **session.to_dict()}


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
    admins.declare(admin, avatar.slug, body.depicts_adult)
    return admin.to_dict()


__all__ = ["router"]
