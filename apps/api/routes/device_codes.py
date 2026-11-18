"""DC1. Redeem a device code for the read grant it carries (``wardrobe.policy.device_codes``).

Public on purpose: the device redeeming a code has no admin session and no grant yet — the code
is its only credential, and the reason this route exists. What keeps it from being a guessing
oracle is the code's own size (about 887 million) and a per-client limit on attempts here: at
``ATTEMPTS_PER_MINUTE``, guessing one of a handful of pending codes before they expire is out of
reach. Any failure answers the same 404, so a caller learns nothing about which codes exist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.dependencies import SettingsDep
from apps.api.ratelimit import SlidingWindow, _too_many, client_address
from wardrobe.policy import device_codes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["access"])

ATTEMPTS_PER_MINUTE = 10
attempts = SlidingWindow()


class Redeem(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@router.post("/device-codes/redeem")
def redeem_device_code(body: Redeem, request: Request, settings: SettingsDep) -> dict:
    """The read grant behind this code, once. 404 for an unknown, used or expired code."""
    wait = attempts.take(client_address(request, settings), ATTEMPTS_PER_MINUTE)
    if wait:
        raise _too_many("too many device-code attempts; wait a minute", wait)
    grant = device_codes.codes.redeem(body.code)
    if grant is None:
        message = "that code is not valid: wrong, used or expired"
        detail = {"reason": "device_code_invalid", "message": message}
        raise HTTPException(status_code=404, detail=detail)
    logger.info("device code redeemed for grant %s", grant.get("id"))
    return grant


__all__ = ["router"]
