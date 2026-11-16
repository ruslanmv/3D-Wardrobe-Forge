"""AC1. Account-scoped access: a signed-in person gets a short-lived capability for their avatars.

The rules are in :mod:`wardrobe.policy.identity` (who is asking), :mod:`wardrobe.policy.grants`
(what the token is) and :mod:`wardrobe.policy.revocations` (taking it back); this is their HTTP
shape, and the admin routes that revoke are with the other admin routes.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import SettingsDep, StoreDep
from wardrobe.policy import grants, identity, revocations

logger = logging.getLogger(__name__)

router = APIRouter(tags=["access"])


_verifiers: dict[tuple, identity.IdentityVerifier] = {}


def identity_verifier_dependency(settings: SettingsDep) -> identity.IdentityVerifier:
    """The deployment's verifier, loaded once per configuration (loading one may import a module
    or open a connection). Tests override this with a controlled identity provider."""
    key = (settings.wardrobe_identity_verifier, settings.wardrobe_identity_secret,
           settings.wardrobe_identity_audience, settings.wardrobe_identity_issuers,
           settings.wardrobe_grant_secret)
    if key not in _verifiers:
        _verifiers.clear()  # one deployment, one configuration: no pile of stale verifiers
        _verifiers[key] = identity.load_verifier(settings)
    return _verifiers[key]


VerifierDep = Annotated[identity.IdentityVerifier, Depends(identity_verifier_dependency)]


class CapabilityRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    #: The library avatars whose private looks are wanted. All of them, or no capability.
    avatars: list[str] = Field(min_length=1, max_length=grants.MAX_SLUGS)
    ttl_seconds: int | None = Field(default=None, alias="ttlSeconds")


def _refuse(code: int, reason: str, message: str) -> HTTPException:
    # Never cached: an intermediary must not hand one person's refusal, or token, to another.
    return HTTPException(status_code=code, detail={"reason": reason, "message": message},
                         headers={"Cache-Control": "no-store"})


@router.get("/access")
def access_status(settings: SettingsDep, verifier: VerifierDep) -> dict:
    """Whether this deployment issues account capabilities. Says nothing about any account."""
    available = bool(grants.usable(settings.wardrobe_grant_secret) and verifier.configured)
    return {"capabilities": available, "header": identity.HEADER, "grantHeader": grants.HEADER,
            "maxTtlSeconds": grants.ACCOUNT_MAX_TTL_S}


@router.post("/access/capabilities", status_code=status.HTTP_201_CREATED)
async def issue_capability(
    body: CapabilityRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    store: StoreDep,
    verifier: VerifierDep,
    x_wardrobe_identity: Annotated[str | None, Header()] = None,
) -> dict:
    """A short-lived read capability for the signed-in account and the avatars it asks for.

    The caller proves who it is with ``X-Wardrobe-Identity`` (whatever the configured verifier
    checks); nothing in the body says who the caller is. Refusals, in the order they are decided:

    * ``503 account_access_unavailable`` — no grant secret, or no identity verifier: nobody can
      be verified here, so nobody is.
    * ``401 identity_unverified`` — no credential, or one the verifier does not accept.
    * ``403 account_revoked`` — the operator has taken this account's access away.
    * ``404 avatar_not_in_library`` — an avatar asked for does not exist here.
    * ``403 adult_verification_required`` / ``403 not_entitled`` — the verified account may not
      read one of the avatars. The whole request is refused: no capability for a subset.

    An admin session is not an identity and gets nothing here; a read grant cannot be
    exchanged for a capability.
    """
    if not grants.usable(settings.wardrobe_grant_secret) or not verifier.configured:
        raise _refuse(503, "account_access_unavailable",
                      "this deployment has no identity verifier; account capabilities are not issued")
    who = await identity.identify(verifier, x_wardrobe_identity)
    if who is None:
        raise _refuse(401, "identity_unverified", "sign in first")
    if await revocations.subject_revoked(store, settings, who.subject):
        logger.info("capability refused: account %s is revoked", who.subject)
        raise _refuse(403, "account_revoked", "this account's access was revoked")
    library = getattr(request.app.state, "library", None)
    wanted = list(dict.fromkeys(body.avatars))
    unknown = [slug for slug in wanted if library is None or library.get(slug) is None]
    if unknown:
        raise _refuse(404, "avatar_not_in_library", "one of the avatars asked for is not in the library")
    for slug in wanted:
        allowed, why = identity.authorize(who, slug)
        if not allowed:
            logger.info("capability refused: account %s, avatar %s, %s", who.subject, slug, why)
            raise _refuse(403, why, "this account may not read that avatar's private looks")
    low, high = grants.ACCOUNT_MIN_TTL_S, grants.ACCOUNT_MAX_TTL_S
    ceiling = max(low, min(int(settings.wardrobe_capability_ttl_s), high))
    ttl = ceiling if body.ttl_seconds is None else max(low, min(body.ttl_seconds, ceiling))
    try:
        token, grant = grants.mint(settings.wardrobe_grant_secret, slugs=wanted, ttl_s=ttl,
                                   subject=who.subject, label="account")
    except grants.GrantError as error:
        raise _refuse(422, "capability_invalid", str(error)) from None
    logger.info("capability %s issued to account %s for %s, expires %s", grant.id, who.subject,
                sorted(grant.slugs), grant.expires)
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "header": grants.HEADER, "expiresIn": ttl, **grant.to_dict()}


__all__ = ["VerifierDep", "identity_verifier_dependency", "router"]
