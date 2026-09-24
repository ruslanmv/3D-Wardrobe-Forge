"""Swimwear and underwear: who may be dressed in them.

A sibling of :mod:`wardrobe.policy.licensing`, with the same shape and the same
trust model: what the model's own file says comes first and cannot be
overridden; beyond that, the caller supplies what the file cannot.

1. **The model's terms.** A VRM 0.x avatar whose meta says
   ``sexualUssageName: Disallow`` is refused swimwear and underwear outright. Its
   author said no, and no attestation changes that — the same rule as a model
   that forbids modification. VRM 1.0 has only ``allowExcessivelySexualUsage``,
   which governs explicit content, not a swimsuit, so it is not read as a no.

2. **An adult declaration.** Anime-styled avatars do not carry an age, and many
   of them read young. Dressing one in lingerie is a decision a person has to
   make about that specific avatar, so the job must carry ``depictsAdult: true``.
   For an upload the caller attests it, like a licence. For the Studio's library
   it comes from ``assets/library/policy.json``, an operator file shipped empty:
   the server, not the browser, supplies it.

Every other category — dresses, skirts, tops, nightwear — is untouched, *unless
the body shows through it*. The gate follows what will render, not the word
for the category: an opaque bodycon dress is a dress; the same dress in sheer
fabric, a lace bodysuit or fishnet stockings needs exactly what a bikini needs.
The planner decides that (``OutfitPlan.requiresAdult``) from three things — an
intimate category, a template that says so, fabric with holes or alpha — and
passes it here as ``requires_adult``.
"""

from __future__ import annotations

from dataclasses import dataclass

from wardrobe.domain.garments import INTIMATE_CATEGORIES
from wardrobe.domain.jobs import FailureReason
from wardrobe.vrm.inspect import LicenseTerms


@dataclass(frozen=True)
class IntimateDecision:
    allowed: bool
    message: str = ""
    reason: FailureReason | None = None


def sexual_usage_disallowed(terms: LicenseTerms | None) -> bool:
    raw = (terms.raw if terms is not None else None) or {}
    return str(raw.get("sexualUssageName", "")).strip().lower() == "disallow"


def evaluate(
    category: str,
    terms: LicenseTerms | None,
    *,
    depicts_adult: bool,
    requires_adult: bool | None = None,
    reason: str | None = None,
) -> IntimateDecision:
    """``requires_adult`` adds to the category rule and never subtracts from it.

    Swimwear and underwear are gated whatever the caller passes; ``requires_adult``
    can only extend the gate to see-through fabric in other categories.
    ``reason`` names what triggered it in the refusal.
    """
    if not (category in INTIMATE_CATEGORIES or requires_adult):
        return IntimateDecision(True)
    what = reason or category
    if sexual_usage_disallowed(terms):
        return IntimateDecision(
            False,
            f"this model's own terms disallow sexual usage, so it cannot be dressed in {what}",
            FailureReason.INTIMATE_NOT_PERMITTED,
        )
    if not depicts_adult:
        return IntimateDecision(
            False,
            f"{what} needs the avatar declared as depicting an adult (avatar.depictsAdult)",
            FailureReason.ADULT_DECLARATION_REQUIRED,
        )
    return IntimateDecision(True, f"{what} permitted: adult declared, model terms allow it")


def gate_reason(category: str, *, see_through: bool) -> str:
    """What to call the garment in a refusal: its category, or its see-through fabric."""
    if category in INTIMATE_CATEGORIES:
        return category
    return f"see-through {category}" if see_through else category


__all__ = ["IntimateDecision", "evaluate", "gate_reason", "sexual_usage_disallowed"]
