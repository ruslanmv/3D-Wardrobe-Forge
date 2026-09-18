"""Licensing policy.

Two sources of truth are combined:

1. the usage terms embedded in the VRM itself (authoritative), and
2. the caller's attestation — typically the VRoid Hub conditions-of-use object
   that 3D-Avatar-Chatbot's VRM Manager already stores per installed avatar.

An attestation can supply terms we cannot read. It can never overrule an
embedded prohibition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wardrobe.domain.avatars import LicenseAttestation
from wardrobe.domain.jobs import FailureReason
from wardrobe.vrm.inspect import LicenseTerms, ModificationPermission

#: VRoid Hub condition values that forbid deriving a new model.
VROID_DISALLOW = {"disallow", "prohibited", "no", "false"}
#: VRoid Hub condition values that permit it.
VROID_ALLOW = {"allow", "everyone", "yes", "true"}


class ModificationNotPermitted(ValueError):
    """Kept for backwards compatibility with the 0.1 scaffold API."""


@dataclass(slots=True)
class LicenseDecision:
    allowed: bool
    message: str
    reason: FailureReason | None = None
    requires_attestation: bool = False
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "message": self.message,
            "reason": str(self.reason) if self.reason else None,
            "requiresAttestation": self.requires_attestation,
            "evidence": self.evidence,
        }


def normalise_vroid_modification(value: str | None) -> ModificationPermission:
    """Map a VRoid Hub ``modification`` condition onto our permission enum."""
    if value is None:
        return ModificationPermission.UNKNOWN
    text = str(value).strip().lower()
    if text in VROID_DISALLOW:
        return ModificationPermission.PROHIBITED
    if text in VROID_ALLOW:
        return ModificationPermission.ALLOWED
    # 'default', 'author', '' and anything unrecognised stay unknown on purpose.
    return ModificationPermission.UNKNOWN


def evaluate(
    embedded: LicenseTerms | None,
    attestation: LicenseAttestation | None = None,
    *,
    strict: bool = True,
) -> LicenseDecision:
    """Decide whether a derived model may be produced from this source."""
    attestation = attestation or LicenseAttestation()
    conditions = {k: str(v) for k, v in (attestation.conditions_of_use or {}).items()}
    attested = normalise_vroid_modification(conditions.get("modification"))
    embedded_permission = embedded.modification if embedded else ModificationPermission.UNKNOWN

    evidence = {
        "embeddedModification": str(embedded_permission),
        "attestedModification": str(attested),
        "embeddedLicenseName": embedded.license_name if embedded else None,
        "userAttested": attestation.user_attests_modification_allowed,
        "strict": strict,
    }

    # 1. An embedded prohibition is final.
    if embedded_permission is ModificationPermission.PROHIBITED:
        return LicenseDecision(
            allowed=False,
            reason=FailureReason.MODIFICATION_NOT_PERMITTED,
            message=(
                "the source model's own VRM metadata prohibits modification"
                + (f" (license: {embedded.license_name})" if embedded and embedded.license_name else "")
            ),
            evidence=evidence,
        )

    # 2. The caller telling us it is disallowed is equally final.
    if attested is ModificationPermission.PROHIBITED:
        return LicenseDecision(
            allowed=False,
            reason=FailureReason.MODIFICATION_NOT_PERMITTED,
            message="the supplied conditions of use prohibit modification",
            evidence=evidence,
        )

    # 3. Embedded permission is enough on its own.
    if embedded_permission in {
        ModificationPermission.ALLOWED,
        ModificationPermission.ALLOWED_WITH_REDISTRIBUTION,
    }:
        return LicenseDecision(
            allowed=True,
            message=f"source model permits modification ({embedded_permission})",
            evidence=evidence,
        )

    # 4. Terms are unknown: fall back to what the caller asserts.
    if attested is ModificationPermission.ALLOWED:
        return LicenseDecision(
            allowed=True,
            message="caller supplied conditions of use permitting modification",
            evidence=evidence,
        )
    if attestation.user_attests_modification_allowed:
        return LicenseDecision(
            allowed=True,
            message="caller explicitly attested that modification is permitted",
            evidence=evidence,
        )
    if not strict:
        return LicenseDecision(
            allowed=True,
            message="usage terms unknown; permitted because strict licensing is disabled",
            evidence=evidence,
        )

    return LicenseDecision(
        allowed=False,
        reason=FailureReason.LICENSE_ATTESTATION_REQUIRED,
        requires_attestation=True,
        message=(
            "the source model's usage terms could not be determined; supply "
            "avatar.license.conditionsOfUse or set userAttestsModificationAllowed"
        ),
        evidence=evidence,
    )


def redistribution_allowed(
    embedded: LicenseTerms | None, attestation: LicenseAttestation | None
) -> bool | None:
    """Whether the derived look may be shared beyond the requesting user."""
    conditions = (attestation.conditions_of_use if attestation else None) or {}
    attested = str(conditions.get("redistribution", "")).strip().lower()
    if attested in VROID_DISALLOW:
        return False
    if attested in VROID_ALLOW:
        return True
    if embedded is not None:
        return embedded.redistribution_allowed
    return None


def require_modification_permission(metadata: dict) -> None:
    """Backwards-compatible helper retained from the 0.1 scaffold.

    Prefer :func:`evaluate`, which distinguishes 'prohibited' from 'unknown'.
    """
    value = str((metadata or {}).get("modification", "")).strip().lower()
    if value in VROID_DISALLOW:
        raise ModificationNotPermitted("source avatar terms prohibit modification")


__all__ = [
    "LicenseDecision",
    "ModificationNotPermitted",
    "VROID_ALLOW",
    "VROID_DISALLOW",
    "evaluate",
    "normalise_vroid_modification",
    "redistribution_allowed",
    "require_modification_permission",
]
