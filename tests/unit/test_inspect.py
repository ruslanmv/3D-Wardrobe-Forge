"""VRM detection, humanoid validation and licence normalisation."""

from __future__ import annotations

import pytest

from wardrobe.vrm.build import CALIBRATION_BODIES, BodyProportions, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import (
    REQUIRED_HUMANOID_BONES,
    ModificationPermission,
    NotAVrm,
    VrmSpec,
    inspect_document,
    validate_humanoid,
)


def test_detects_vrm1(vrm_bytes: bytes):
    info = inspect_document(GltfDocument.from_bytes(vrm_bytes))
    assert info.spec is VrmSpec.VRM1
    assert set(info.humanoid_bones) >= REQUIRED_HUMANOID_BONES
    assert info.title == CALIBRATION_BODIES[1].name


def test_detects_vrm0(vrm0_bytes: bytes):
    info = inspect_document(GltfDocument.from_bytes(vrm0_bytes))
    assert info.spec is VrmSpec.VRM0
    assert set(info.humanoid_bones) >= REQUIRED_HUMANOID_BONES


def test_plain_glb_is_not_a_vrm(vrm_bytes: bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    document.gltf.pop("extensions")
    with pytest.raises(NotAVrm):
        inspect_document(document)


def test_humanoid_validation_passes_on_a_complete_rig(vrm_bytes: bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    assert validate_humanoid(document, inspect_document(document)) == []


def test_missing_bone_is_reported(vrm_bytes: bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    del document.gltf["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]["leftHand"]

    issues = validate_humanoid(document, inspect_document(document))
    assert any("missing required humanoid bones" in issue and "leftHand" in issue for issue in issues)


def test_dangling_bone_node_is_reported(vrm_bytes: bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    document.gltf["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]["head"]["node"] = 9999

    issues = validate_humanoid(document, inspect_document(document))
    assert any("does not exist" in issue for issue in issues)


@pytest.mark.parametrize(
    ("modification", "expected"),
    [
        ("allowModificationRedistribution", ModificationPermission.ALLOWED_WITH_REDISTRIBUTION),
        ("allowModification", ModificationPermission.ALLOWED),
        ("prohibited", ModificationPermission.PROHIBITED),
    ],
)
def test_vrm1_modification_terms(modification: str, expected: ModificationPermission):
    body = BodyProportions(name="terms", modification=modification)
    info = inspect_document(GltfDocument.from_bytes(build_vrm(body, spec="VRM1")))
    assert info.license.modification is expected


@pytest.mark.parametrize(
    ("license_name", "expected"),
    [
        ("CC0", ModificationPermission.ALLOWED),
        ("CC_BY", ModificationPermission.ALLOWED),
        ("Redistribution_Prohibited", ModificationPermission.ALLOWED),
        ("CC_BY_ND", ModificationPermission.PROHIBITED),
        ("CC_BY_NC_ND", ModificationPermission.PROHIBITED),
        ("Other", ModificationPermission.UNKNOWN),
    ],
)
def test_vrm0_license_names_map_to_modification_rights(
    vrm0_bytes: bytes, license_name: str, expected: ModificationPermission
):
    document = GltfDocument.from_bytes(vrm0_bytes)
    document.gltf["extensions"]["VRM"]["meta"]["licenseName"] = license_name
    assert inspect_document(document).license.modification is expected


def test_expressions_are_listed(vrm_bytes: bytes):
    info = inspect_document(GltfDocument.from_bytes(vrm_bytes))
    assert "blink" in info.expressions
    assert "happy" in info.expressions
