"""BS1. Who may have a body surface built, and which.

Three questions with three different owners, asked in this order — the first no wins:

1. **The model's own terms** (its author). For the adult capability the reading is stricter
   than for a swimsuit: VRM 0.x ``sexualUssageName: Disallow`` *and* VRM 1.0
   ``allowExcessivelySexualUsage: false`` both refuse. A swimsuit is not sexual expression;
   a visible anatomical surface may be, and the author's ``false`` is read as meaning it.
2. **The operator's switch** (``WARDROBE_ADULT_BODY_SURFACE``), off by default. A deployment
   that never turned it on cannot serve an adult profile, whatever a caller sends.
3. **The adult declaration** for this avatar (``avatar.depictsAdult``) — supplied by the
   server for the library and the admin session, attested by the caller for an upload,
   never by a prompt. Age is never inferred, so an avatar without it is refused.

A ``body_collision`` profile — a smoothed collider for fitting, nothing visible — needs none of
this: it changes no pixel of her and serves every garment, opaque ones included. Nor does a
``body_surface`` profile, whose regions are not intimate (a navel): it is a modification of
her model like any garment, and the licence stage has already checked that she may be modified.
"""

from __future__ import annotations

from dataclasses import dataclass

from wardrobe.body_surface.contract import Capability
from wardrobe.policy.intimate import sexual_usage_disallowed


@dataclass(frozen=True)
class SurfaceDecision:
    allowed: bool
    message: str = ""
    #: "model-terms", "operator-disabled", "adult-declaration" — which question said no.
    refused_by: str | None = None


def explicit_usage_disallowed(terms) -> bool:
    """VRM 1.0's ``allowExcessivelySexualUsage``, read strictly: absent counts as not allowed."""
    raw = (terms.raw if terms is not None else None) or {}
    if "allowExcessivelySexualUsage" in raw:
        return raw.get("allowExcessivelySexualUsage") is not True
    return False  # a VRM 0.x model says what it says through sexualUssageName


def evaluate(capability: Capability, terms, *, operator_enabled: bool,
             depicts_adult: bool) -> SurfaceDecision:
    if capability is Capability.BODY_COLLISION:
        return SurfaceDecision(True, "collision body: fitting only, nothing about her is shown differently")
    if capability is Capability.BODY_SURFACE:
        return SurfaceDecision(True, "body surface without intimate regions: the licence stage's "
                                     "modification check is the gate, as for any garment")
    if sexual_usage_disallowed(terms) or explicit_usage_disallowed(terms):
        return SurfaceDecision(False, "this model's own terms do not allow sexual expression, so its body "
                                      "surface is not changed", "model-terms")
    if not operator_enabled:
        return SurfaceDecision(False, "adult body surfaces are not enabled on this server "
                                      "(WARDROBE_ADULT_BODY_SURFACE)", "operator-disabled")
    if not depicts_adult:
        return SurfaceDecision(False, "an adult body surface needs the avatar declared as depicting an adult "
                                      "(avatar.depictsAdult)", "adult-declaration")
    return SurfaceDecision(True, "adult body surface permitted: operator enabled, adult declared, "
                                 "model terms allow it")


__all__ = ["SurfaceDecision", "evaluate", "explicit_usage_disallowed"]
