"""Licensing policy — the gate that runs before any 3D work."""

from __future__ import annotations

import pytest

from wardrobe.domain.avatars import LicenseAttestation
from wardrobe.domain.jobs import FailureReason
from wardrobe.policy.licensing import (
    ModificationNotPermitted,
    evaluate,
    normalise_vroid_modification,
    redistribution_allowed,
    require_modification_permission,
)
from wardrobe.vrm.inspect import LicenseTerms, ModificationPermission


def terms(modification: ModificationPermission, **kwargs) -> LicenseTerms:
    return LicenseTerms(modification=modification, **kwargs)


# ----------------------------------------------------------------------
# embedded terms
# ----------------------------------------------------------------------
def test_embedded_permission_is_sufficient():
    decision = evaluate(terms(ModificationPermission.ALLOWED))
    assert decision.allowed


def test_embedded_prohibition_is_rejected():
    decision = evaluate(terms(ModificationPermission.PROHIBITED, license_name="CC_BY_ND"))
    assert not decision.allowed
    assert decision.reason is FailureReason.MODIFICATION_NOT_PERMITTED
    assert "CC_BY_ND" in decision.message


def test_attestation_cannot_override_an_embedded_prohibition():
    """The whole point of the policy: the model's own terms win."""
    decision = evaluate(
        terms(ModificationPermission.PROHIBITED),
        LicenseAttestation(
            userAttestsModificationAllowed=True,
            conditionsOfUse={"modification": "allow"},
        ),
    )
    assert not decision.allowed
    assert decision.reason is FailureReason.MODIFICATION_NOT_PERMITTED


# ----------------------------------------------------------------------
# unknown terms
# ----------------------------------------------------------------------
def test_unknown_terms_require_attestation_in_strict_mode():
    decision = evaluate(terms(ModificationPermission.UNKNOWN), strict=True)
    assert not decision.allowed
    assert decision.requires_attestation
    assert decision.reason is FailureReason.LICENSE_ATTESTATION_REQUIRED


def test_unknown_terms_are_allowed_when_strict_mode_is_off():
    assert evaluate(terms(ModificationPermission.UNKNOWN), strict=False).allowed


def test_vroid_conditions_can_supply_unknown_terms():
    decision = evaluate(
        terms(ModificationPermission.UNKNOWN),
        LicenseAttestation(conditionsOfUse={"modification": "allow"}),
    )
    assert decision.allowed


def test_explicit_user_attestation_is_accepted():
    decision = evaluate(
        terms(ModificationPermission.UNKNOWN),
        LicenseAttestation(userAttestsModificationAllowed=True),
    )
    assert decision.allowed


def test_vroid_conditions_can_forbid_modification():
    decision = evaluate(
        terms(ModificationPermission.UNKNOWN),
        LicenseAttestation(conditionsOfUse={"modification": "disallow"}),
    )
    assert not decision.allowed
    assert decision.reason is FailureReason.MODIFICATION_NOT_PERMITTED


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("allow", ModificationPermission.ALLOWED),
        ("everyone", ModificationPermission.ALLOWED),
        ("disallow", ModificationPermission.PROHIBITED),
        ("default", ModificationPermission.UNKNOWN),
        ("author", ModificationPermission.UNKNOWN),
        (None, ModificationPermission.UNKNOWN),
    ],
)
def test_vroid_value_mapping(value, expected):
    assert normalise_vroid_modification(value) is expected


def test_redistribution_prefers_the_attestation():
    assert redistribution_allowed(
        terms(ModificationPermission.ALLOWED, redistribution_allowed=True),
        LicenseAttestation(conditionsOfUse={"redistribution": "disallow"}),
    ) is False


def test_decision_serialises_for_the_api():
    payload = evaluate(terms(ModificationPermission.UNKNOWN)).to_dict()
    assert payload["requiresAttestation"] is True
    assert payload["evidence"]["embeddedModification"] == "unknown"


# ----------------------------------------------------------------------
# legacy helper
# ----------------------------------------------------------------------
def test_legacy_helper_still_rejects_explicit_prohibition():
    with pytest.raises(ModificationNotPermitted):
        require_modification_permission({"modification": "disallow"})


def test_legacy_helper_allows_unknown_metadata():
    require_modification_permission({})
