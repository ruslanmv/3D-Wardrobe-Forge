"""Procedural garment geometry, skin binding and the clearance checks."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.engines.geometry_checks import (
    BodyRadialIndex,
    measure_clearance,
    pose_stress_test,
    resolve_clearance,
)
from wardrobe.geometry.mesh import Mesh, concatenate
from wardrobe.geometry.procedural import FitParameters, Ring, build_garment, loft, sweep
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.skinning import bind_mesh, bones_for_coverage, build_bone_segments, weight_report

CATEGORIES = ["dress", "skirt", "top", "jacket", "trousers", "shoes"]


@pytest.fixture(scope="module")
def measured():
    data = build_vrm(CALIBRATION_BODIES[1], spec="VRM1")
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    return document, info, measure_body(document, info)


# ----------------------------------------------------------------------
# primitives
# ----------------------------------------------------------------------
def test_loft_is_watertight_in_index_space():
    mesh = loft([Ring(0.0, 0.2, 0.15), Ring(1.0, 0.25, 0.18)], segments=8)
    assert mesh.validate() == []
    assert mesh.triangle_count == 8 * 2


def test_loft_caps_add_geometry():
    open_mesh = loft([Ring(0.0, 0.2, 0.2), Ring(1.0, 0.2, 0.2)], segments=8)
    capped = loft([Ring(0.0, 0.2, 0.2), Ring(1.0, 0.2, 0.2)], segments=8, cap_top=True, cap_bottom=True)
    assert capped.triangle_count == open_mesh.triangle_count + 16


def test_loft_needs_two_rings():
    with pytest.raises(ValueError, match="at least two rings"):
        loft([Ring(0.0, 0.1, 0.1)])


def test_sweep_follows_the_path():
    path = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.5, 2.0, 0.0]])
    mesh = sweep(path, [0.1, 0.08, 0.06], segments=8)
    assert mesh.validate() == []
    low, high = mesh.bounds()
    assert high[1] == pytest.approx(2.0, abs=0.12)


def test_normals_are_unit_length():
    mesh = loft([Ring(0.0, 0.2, 0.2), Ring(1.0, 0.2, 0.2)], segments=12)
    lengths = np.linalg.norm(mesh.normals, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-5)


def test_concatenate_offsets_indices():
    a = loft([Ring(0.0, 0.1, 0.1), Ring(0.5, 0.1, 0.1)], segments=6)
    b = loft([Ring(1.0, 0.1, 0.1), Ring(1.5, 0.1, 0.1)], segments=6)
    merged = concatenate([a, b])
    assert merged.vertex_count == a.vertex_count + b.vertex_count
    assert merged.validate() == []


def test_mesh_validation_catches_bad_indices():
    mesh = Mesh(positions=np.zeros((3, 3), dtype=np.float32), indices=np.array([0, 1, 9], dtype=np.uint32))
    assert any("does not exist" in issue for issue in mesh.validate())


# ----------------------------------------------------------------------
# garments
# ----------------------------------------------------------------------
@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_builds(measured, category: str):
    _, _, measurements = measured
    mesh = build_garment(category, FitParameters(measurements=measurements))
    assert mesh.validate() == []
    assert mesh.vertex_count > 0


def test_unknown_category_is_rejected(measured):
    _, _, measurements = measured
    with pytest.raises(ValueError, match="unsupported garment category"):
        build_garment("spacesuit", FitParameters(measurements=measurements))


def test_flare_widens_the_hem(measured):
    _, _, measurements = measured
    params = FitParameters(measurements=measurements)
    narrow = build_garment("skirt", params, silhouette="pencil")
    wide = build_garment("skirt", params, silhouette="ball-gown")
    assert wide.bounds()[1][0] > narrow.bounds()[1][0]


def test_hem_length_is_honoured(measured):
    _, _, measurements = measured
    params = FitParameters(measurements=measurements)
    mini = build_garment("dress", params, hem="mini")
    floor = build_garment("dress", params, hem="floor")
    assert floor.bounds()[0][1] < mini.bounds()[0][1]


def test_garment_scales_with_the_body():
    """One template, four bodies: the shell must track each one's size."""
    widths = []
    for body in CALIBRATION_BODIES:
        document = GltfDocument.from_bytes(build_vrm(body, spec="VRM1"))
        measurements = measure_body(document, inspect_document(document))
        mesh = build_garment("dress", FitParameters(measurements=measurements))
        widths.append(mesh.bounds()[1][0] - mesh.bounds()[0][0])

    assert widths[3] > widths[0]  # broad is wider than petite


# ----------------------------------------------------------------------
# binding
# ----------------------------------------------------------------------
def test_binding_produces_normalised_weights(measured):
    _, info, measurements = measured
    mesh = build_garment("dress", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["chest", "waist", "hips", "upperLegs"])
    )
    bind_mesh(mesh, segments)

    report = weight_report(mesh, segments)
    assert report["valid"]
    assert report["maxInfluences"] <= 4
    assert np.allclose(mesh.weights.sum(axis=1), 1.0, atol=1e-4)


def test_binding_only_uses_the_declared_bones(measured):
    _, info, measurements = measured
    mesh = build_garment("skirt", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["waist", "hips", "upperLegs"])
    )
    bind_mesh(mesh, segments)
    assert "head" not in weight_report(mesh, segments)["bonesUsed"]


def test_binding_without_bones_is_an_error(measured):
    _, _, measurements = measured
    mesh = build_garment("dress", FitParameters(measurements=measurements))
    with pytest.raises(ValueError, match="without any candidate bones"):
        bind_mesh(mesh, [])


def test_separate_pieces_do_not_bind_across_the_midline(measured):
    """A left shoe must never pick up a right-leg bone.

    Regression: inverse-distance weighting alone bound near-midline shoe
    vertices to the opposite shin, so the pair tore apart as soon as the legs
    swung in opposite directions.
    """
    _, info, measurements = measured
    mesh = build_garment("shoes", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["feet", "lowerLegs"])
    )
    bind_mesh(mesh, segments)

    names = [segment.name for segment in segments]
    centre = np.median([s.head[0] for s in segments])

    for vertex in range(mesh.vertex_count):
        side = "left" if mesh.positions[vertex, 0] > centre else "right"
        opposite = "right" if side == "left" else "left"
        for joint, weight in zip(mesh.joints[vertex], mesh.weights[vertex], strict=True):
            if weight > 1e-4:
                assert not names[joint].startswith(opposite), (
                    f"vertex {vertex} on the {side} is weighted to {names[joint]}"
                )


def test_one_sided_pieces_deform_rigidly(measured):
    """With correct binding, a walk pose must not distort the shoes at all."""
    _, info, measurements = measured
    mesh = build_garment("shoes", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["feet", "lowerLegs"])
    )
    bind_mesh(mesh, segments)

    pivots = {name: np.array(value) for name, value in measurements.bone_positions.items()}
    results = pose_stress_test(mesh, segments, pivots)
    assert results["walk"]["maxEdgeStretch"] == pytest.approx(1.0, abs=0.01)


def test_a_skirt_still_blends_between_both_legs(measured):
    """The midline rule must not turn a continuous skirt into two halves."""
    _, info, measurements = measured
    mesh = build_garment("skirt", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["waist", "hips", "upperLegs"])
    )
    bind_mesh(mesh, segments)

    names = [segment.name for segment in segments]
    used = {
        names[j]
        for row, weights in zip(mesh.joints, mesh.weights, strict=True)
        for j, w in zip(row, weights, strict=True)
        if w > 1e-4
    }
    assert "leftUpperLeg" in used and "rightUpperLeg" in used


def test_connected_components_are_detected(measured):
    from wardrobe.vrm.skinning import connected_components

    _, _, measurements = measured
    shoes = build_garment("shoes", FitParameters(measurements=measurements))
    assert len(np.unique(connected_components(shoes))) == 2

    skirt = build_garment("skirt", FitParameters(measurements=measurements))
    assert len(np.unique(connected_components(skirt))) == 1


def test_pose_tests_account_for_parent_bones(measured):
    """Rotating a shin must carry the foot with it, or boots read as torn."""
    _, info, measurements = measured
    mesh = build_garment("shoes", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["feet", "lowerLegs"])
    )
    bind_mesh(mesh, segments)

    pivots = {name: np.array(value) for name, value in measurements.bone_positions.items()}
    results = pose_stress_test(mesh, segments, pivots)
    # 'sit' bends knee and hip; a boot rigidly attached below the knee should
    # follow exactly.
    assert results["sit"]["maxEdgeStretch"] == pytest.approx(1.0, abs=0.01)


def test_pose_tests_pass_on_a_correctly_bound_garment(measured):
    _, info, measurements = measured
    mesh = build_garment("dress", FitParameters(measurements=measurements))
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["chest", "waist", "hips", "upperLegs"])
    )
    bind_mesh(mesh, segments)

    results = pose_stress_test(mesh, segments)
    assert results["checked"] and results["passed"]
    assert results["sit"]["applies"]


# ----------------------------------------------------------------------
# clearance
# ----------------------------------------------------------------------
def test_clearance_resolution_pushes_the_shell_outside(measured):
    from wardrobe.engines.geometry_checks import body_points, select_region_points

    document, info, measurements = measured

    # Index the torso and legs only, exactly as the pipeline does: the radial
    # index is centred on the body's vertical axis, so a T-posed arm would
    # otherwise dominate every band at shoulder height.
    points = body_points(document)
    segments = build_bone_segments(info.humanoid_bones, measurements, list(info.humanoid_bones))
    points = points[
        select_region_points(
            points, segments, {"hips", "spine", "chest", "upperChest", "leftUpperLeg", "rightUpperLeg"}
        )
    ]
    index = BodyRadialIndex(points)

    # A slightly too-small garment starts inside the body.
    mesh = build_garment("dress", FitParameters(measurements=measurements))
    mesh.positions[:, 0] *= 0.85
    mesh.positions[:, 2] *= 0.85

    before = measure_clearance(mesh, index, 0.006)
    assert before.violations > 0
    assert before.min_clearance_mm < 0  # actually inside the body

    moved = resolve_clearance(mesh, index, 0.006)
    after = measure_clearance(mesh, index, 0.006)

    assert moved > 0
    assert after.violations == 0
    assert after.min_clearance_mm > before.min_clearance_mm
    assert after.min_clearance_mm >= 0


def test_an_absurdly_undersized_garment_is_reported_not_silently_inflated(measured):
    """The push is capped, so a hopeless fit stays visible in the report.

    Quietly expanding a garment by 12 cm would hide a real planning failure
    behind a passing clipping check.
    """
    from wardrobe.engines.geometry_checks import body_points, push_limit, select_region_points

    document, info, measurements = measured
    points = body_points(document)
    segments = build_bone_segments(info.humanoid_bones, measurements, list(info.humanoid_bones))
    points = points[
        select_region_points(points, segments, {"hips", "spine", "chest", "upperChest"})
    ]
    index = BodyRadialIndex(points)

    mesh = build_garment("dress", FitParameters(measurements=measurements))
    mesh.positions[:, 0] *= 0.2
    mesh.positions[:, 2] *= 0.2

    deficit = -measure_clearance(mesh, index, 0.006).min_clearance_mm / 1000.0
    assert deficit > push_limit(index, 0.006)

    resolve_clearance(mesh, index, 0.006)
    after = measure_clearance(mesh, index, 0.006)
    assert after.violations > 0


def test_empty_body_index_is_handled():
    index = BodyRadialIndex(np.zeros((0, 3)))
    mesh = loft([Ring(0.0, 0.2, 0.2), Ring(1.0, 0.2, 0.2)], segments=8)
    assert measure_clearance(mesh, index, 0.006).checked is False
    assert resolve_clearance(mesh, index, 0.006) == 0
