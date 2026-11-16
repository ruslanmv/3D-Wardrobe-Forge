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


#: AF3. The review that a character is clearly adult in design, per exact source file.
REVIEWS_SCHEMA = "wardrobe.bodySurface.adultDesignReviews.v1"
REVIEW_FIELDS = ("outcome", "reviewer", "date", "evidence")


def design_review(root, source_sha256: str | None) -> dict | None:
    """The recorded adult-design review of this exact source, or None.

    A declaration (``depictsAdult``) is a statement about a character; whether a stylised design
    reads as clearly adult is a judgement a person makes looking at it. That judgement is recorded
    server-side in ``<body surface root>/adult-design-reviews.json``, keyed by the SHA-256 of the
    reviewed VRM's bytes, so it belongs to the file that was looked at: a caller cannot send it, and
    an edited or swapped file is not covered. Unreadable or incomplete records count as no review.
    """
    import json
    from pathlib import Path

    if not source_sha256:
        return None
    try:
        data = json.loads((Path(root) / "adult-design-reviews.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema") != REVIEWS_SCHEMA:
        return None
    review = (data.get("reviews") or {}).get(source_sha256)
    if not isinstance(review, dict) or any(not review.get(k) for k in REVIEW_FIELDS):
        return None
    return review


def evaluate(capability: Capability, terms, *, operator_enabled: bool,
             depicts_adult: bool, intimate: bool = False,
             design_reviewed: dict | None = None) -> SurfaceDecision:
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
    # AF3. Fourth question, for intimate regions only: a person reviewed this exact file's design
    # and found the character clearly adult. A declaration alone does not open anatomy detail.
    if intimate and (design_reviewed or {}).get("outcome") != "clearly-adult":
        return SurfaceDecision(False, "intimate body detail needs a recorded review that this exact avatar "
                                      "is clearly adult in design (adult-design-reviews.json)",
                               "adult-design-review")
    return SurfaceDecision(True, "adult body surface permitted: operator enabled, adult declared, "
                                 "model terms allow it")


__all__ = ["REVIEWS_SCHEMA", "SurfaceDecision", "design_review", "evaluate", "explicit_usage_disallowed"]
