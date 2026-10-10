"""Pipeline exceptions carrying a machine-readable failure reason."""

from __future__ import annotations

from wardrobe.domain.jobs import FailureReason


class WardrobeError(Exception):
    """Base class: every pipeline failure maps onto a stable client-facing code."""

    reason: FailureReason = FailureReason.INTERNAL

    def __init__(self, message: str, *, reason: FailureReason | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        if reason is not None:
            self.reason = reason
        self.detail = detail or {}


class SourceRejected(WardrobeError):
    """The source avatar cannot be accepted (format, size, reachability)."""

    reason = FailureReason.SOURCE_NOT_A_VRM


class LicenseRejected(WardrobeError):
    reason = FailureReason.MODIFICATION_NOT_PERMITTED


class AttestationRequired(WardrobeError):
    reason = FailureReason.LICENSE_ATTESTATION_REQUIRED


class IntimateNotPermitted(WardrobeError):
    """The model's own terms disallow sexual usage; swimwear and underwear are refused."""

    reason = FailureReason.INTIMATE_NOT_PERMITTED


class AdultDeclarationRequired(WardrobeError):
    """Swimwear and underwear need the avatar declared as depicting an adult."""

    reason = FailureReason.ADULT_DECLARATION_REQUIRED


class BodyIncomplete(WardrobeError):
    """Taking off her clothes would expose missing body geometry; nothing is invented to fill it."""

    reason = FailureReason.BODY_INCOMPLETE


class FoundationOverClothing(WardrobeError):
    """Underwear would be fitted over clothes she keeps on; it goes on her body or not at all."""

    reason = FailureReason.FOUNDATION_OVER_CLOTHING


class PaintedClothingShows(WardrobeError):
    """Clothes painted on her skin would show round the underwear; her skin is never repainted."""

    reason = FailureReason.PAINTED_CLOTHING_SHOWS


class BodyArtNeedsLook(WardrobeError):
    """BA6. A tattoo-only job on something that is not a finished Forge look."""

    reason = FailureReason.BODY_ART_NEEDS_LOOK


class BodyArtNotApplied(WardrobeError):
    """BA6. A tattoo-only job none of whose tattoos could be made: there is no new look."""

    reason = FailureReason.BODY_ART_NOT_APPLIED


class NotHumanoid(WardrobeError):
    reason = FailureReason.SOURCE_NOT_HUMANOID


class PlanningError(WardrobeError):
    reason = FailureReason.NO_TEMPLATE_MATCH


class ProviderError(WardrobeError):
    reason = FailureReason.PROVIDER_ERROR


class FittingError(WardrobeError):
    reason = FailureReason.FITTING_FAILED


class OutputInvalid(WardrobeError):
    reason = FailureReason.OUTPUT_INVALID


__all__ = [
    "WardrobeError",
    "SourceRejected",
    "LicenseRejected",
    "AttestationRequired",
    "IntimateNotPermitted",
    "AdultDeclarationRequired",
    "BodyIncomplete",
    "FoundationOverClothing",
    "BodyArtNeedsLook",
    "BodyArtNotApplied",
    "NotHumanoid",
    "PlanningError",
    "ProviderError",
    "FittingError",
    "OutputInvalid",
]
