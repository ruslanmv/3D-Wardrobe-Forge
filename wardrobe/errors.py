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
    "NotHumanoid",
    "PlanningError",
    "ProviderError",
    "FittingError",
    "OutputInvalid",
]
