"""BI2. The request's read grant (wardrobe.policy.grants), as a FastAPI dependency.

A grant only ever widens what a route *reads*: routes ask ``can_read_private(admin, grant, slug)``
and nothing that writes accepts a grant.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from apps.api.dependencies import SettingsDep
from wardrobe.policy.grants import Grant, verify


def current_grant(
    settings: SettingsDep, x_wardrobe_grant: Annotated[str | None, Header()] = None
) -> Grant | None:
    revoked = [g.strip() for g in settings.wardrobe_grant_revoked.split(",") if g.strip()]
    return verify(settings.wardrobe_grant_secret, x_wardrobe_grant, revoked=revoked)


GrantDep = Annotated[Grant | None, Depends(current_grant)]


def can_read_private(admin, grant: Grant | None, slug: str | None) -> bool:
    """An admin session reads every private look; a grant reads only its own avatars'."""
    return admin is not None or (grant is not None and grant.covers(slug))


__all__ = ["GrantDep", "can_read_private", "current_grant"]
