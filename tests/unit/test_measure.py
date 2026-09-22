"""Body measurement."""

from __future__ import annotations

import pytest

from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import MeasurementError, measure_body


def _measure(data: bytes):
    document = GltfDocument.from_bytes(data)
    return measure_body(document, inspect_document(document))


@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda b: b.name)
def test_measured_height_matches_the_declared_height(body):
    measurements = _measure(build_vrm(body, spec="VRM1"))
    assert measurements.height_m == pytest.approx(body.height, rel=0.01)


@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda b: b.name)
def test_shoulder_width_is_measured_from_the_bones(body):
    measurements = _measure(build_vrm(body, spec="VRM1"))
    assert measurements.confidence["shoulder"] == 1.0
    assert measurements.shoulder_width_m == pytest.approx(body.shoulder_width, rel=0.12)


def test_bodies_are_distinguishable():
    """The calibration set must actually differ, or M2 proves nothing."""
    heights = {b.name: _measure(build_vrm(b, spec="VRM1")).height_m for b in CALIBRATION_BODIES}
    assert max(heights.values()) - min(heights.values()) > 0.3

    hips = {b.name: _measure(build_vrm(b, spec="VRM1")).hip_width_m for b in CALIBRATION_BODIES}
    assert max(hips.values()) / min(hips.values()) > 1.4


def test_all_humanoid_bones_are_positioned(vrm_bytes: bytes):
    measurements = _measure(vrm_bytes)
    for bone in ("hips", "head", "leftHand", "rightFoot"):
        assert bone in measurements.bone_positions


def test_limb_lengths_are_measured_not_estimated(vrm_bytes: bytes):
    measurements = _measure(vrm_bytes)
    assert measurements.confidence["arm"] == 1.0
    assert measurements.confidence["leg"] == 1.0
    assert measurements.arm_length_m > 0.2
    assert measurements.leg_length_m > 0.3


def test_measurements_serialise_to_camel_case(vrm_bytes: bytes):
    payload = _measure(vrm_bytes).to_dict()
    assert {"heightM", "shoulderWidthM", "hipWidthM", "bonePositions"} <= set(payload)


def test_rig_without_hips_is_rejected(vrm_bytes: bytes):
    document = GltfDocument.from_bytes(vrm_bytes)
    info = inspect_document(document)
    info.humanoid_bones.pop("hips")
    with pytest.raises(MeasurementError, match="hips"):
        measure_body(document, info)


def test_scale_relative_to_reports_ratios():
    petite = _measure(build_vrm(CALIBRATION_BODIES[0], spec="VRM1"))
    tall = _measure(build_vrm(CALIBRATION_BODIES[2], spec="VRM1"))
    ratios = tall.scale_relative_to(petite)
    assert ratios["height"] > 1.15
