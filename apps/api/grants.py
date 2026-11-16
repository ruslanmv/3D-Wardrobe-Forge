"""BI2. The request's read grant (wardrobe.policy.grants), as a FastAPI dependency.

A grant only ever widens what a route *reads*: routes ask ``can_read_private(admin, grant, slug)``
and nothing that writes accepts a grant.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from apps.api.dependencies import SettingsDep, StoreDep
from wardrobe.pipeline import prebuilt
from wardrobe.policy import revocations
from wardrobe.policy.grants import Grant, verify


async def current_grant(
    settings: SettingsDep, store: StoreDep, x_wardrobe_grant: Annotated[str | None, Header()] = None
) -> Grant | None:
    """The request's grant, or None: not sent, not ours, expired, or taken back (AC1)."""
    grant = verify(settings.wardrobe_grant_secret, x_wardrobe_grant)
    if grant is None or await revocations.revoked(store, settings, grant):
        return None
    return grant


GrantDep = Annotated[Grant | None, Depends(current_grant)]


def can_read_private(admin, grant: Grant | None, slug: str | None, account: str | None = None) -> bool:
    """An admin session reads every private look; a grant reads only its own avatars'.

    AC1. ``account`` is the account a look's own marker names, when it names one: then only
    that account's capability reads it (``Grant.covers``).
    """
    return admin is not None or (grant is not None and grant.covers(slug, account))


def reader_account(admin, grant: Grant | None):
    """Whose account-bound looks a listing shows: everyone's to an admin session, a capability's
    own, and none to an operator grant or an anonymous caller."""
    if admin is not None:
        return prebuilt.ANY_ACCOUNT
    return grant.subject if grant is not None else None


__all__ = ["GrantDep", "can_read_private", "current_grant", "reader_account"]
