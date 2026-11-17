"""UX1. Any local VRM can be checked without confusing normal clothing with bare readiness."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.vrm_compatibility import assess, inspect_file, main
from wardrobe.vrm.inspect import LicenseTerms, ModificationPermission, VrmSpec


def info(terms=None):
    return SimpleNamespace(
        spec=VrmSpec.VRM1,
        title="Test character",
        license=terms or LicenseTerms(
            modification=ModificationPermission.ALLOWED,
            raw={"allowExcessivelySexualUsage": True},
        ),
    )


def test_normal_clothes_do_not_require_any_adult_design_review():
    result = assess(info(), [])
    assert result["ordinaryClothing"]["status"] == "ready-for-wardrobe"
    assert result["privateClothing"]["status"] == "needs-session-and-operator-check"
    assert result["bareBody"]["status"] == "needs-reviewed-adult-body-assets"


def test_explicit_source_modification_prohibition_blocks_all_derived_outfits():
    t = LicenseTerms(modification=ModificationPermission.PROHIBITED)
    result = assess(info(t), [])
    assert all(result[k]["status"] == "blocked-source-terms"
               for k in ("ordinaryClothing", "privateClothing", "bareBody"))


def test_unknown_modification_terms_require_rights_evidence_not_a_fake_approval():
    t = LicenseTerms(modification=ModificationPermission.UNKNOWN)
    result = assess(info(t), [])
    assert all(result[k]["status"] == "needs-license-evidence"
               for k in ("ordinaryClothing", "privateClothing", "bareBody"))


def test_vrm0_sexual_usage_prohibition_does_not_block_ordinary_clothing():
    t = LicenseTerms(modification=ModificationPermission.ALLOWED,
                     raw={"sexualUssageName": "Disallow"})
    result = assess(info(t), [])
    assert result["ordinaryClothing"]["status"] == "ready-for-wardrobe"
    assert result["privateClothing"]["status"] == "blocked-source-terms"
    assert result["bareBody"]["status"] == "blocked-source-terms"


def test_vrm1_excessive_usage_false_does_not_block_ordinary_clothes():
    t = LicenseTerms(modification=ModificationPermission.ALLOWED,
                     raw={"allowExcessivelySexualUsage": False})
    result = assess(info(t), [])
    assert result["ordinaryClothing"]["status"] == "ready-for-wardrobe"
    assert result["bareBody"]["status"] == "blocked-source-terms"


def test_invalid_humanoid_is_not_claimed_ready():
    result = assess(info(), ["missing required humanoid bones: leftHand"])
    assert result["rigValid"] is False
    assert all(result[k]["status"] == "blocked-invalid-rig"
               for k in ("ordinaryClothing", "privateClothing", "bareBody"))


def test_inspect_real_generated_vrm_file(tmp_path, vrm_bytes):
    source = tmp_path / "custom.vrm"
    source.write_bytes(vrm_bytes)
    result = inspect_file(source)
    assert result["spec"] == "VRM1"
    assert len(result["sourceSha256"]) == 64
    assert result["sourceBytes"] == len(vrm_bytes)
    assert result["advisoryOnly"] is True


def test_empty_file_is_rejected_without_claiming_any_capability(tmp_path, capsys):
    source = tmp_path / "empty.vrm"
    source.write_bytes(b"")
    assert main([str(source)]) == 2
    assert '"valid": false' in capsys.readouterr().out.lower()


def test_oversized_file_is_rejected_before_parsing(tmp_path, monkeypatch):
    from tools import vrm_compatibility

    source = tmp_path / "a.vrm"
    source.write_bytes(b"x")
    monkeypatch.setattr(vrm_compatibility, "MAX_BYTES", 0)
    with pytest.raises(ValueError, match="exceeds"):
        inspect_file(source)
