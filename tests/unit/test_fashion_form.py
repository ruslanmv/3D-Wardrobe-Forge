"""L1: the fashion-fit forms, held to their size chart and to having no detail; and the landmarks measured on them.

The calibration bodies cannot judge lingerie (no bust, no crotch, no feet, a
ridged hip). The forms can, and these tests keep what makes them usable: a tape
round them reads the chart; they are declared adult by the repository's policy
file and by nothing else; their surface is smooth by a curvature bound, which
is what "no anatomical detail" means in numbers; and the landmarks a pattern
block is placed on are found on them, on the calibration bodies (by formula,
with a warning), and on the library avatars.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wardrobe.lingerie.landmarks import landmarks_for_document
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import (
    FASHION_FIT_BODIES,
    _torso,
    build_fit_form,
    build_fit_form_mesh,
    chart,
    convex_girth,
    form_landmarks,
    positions_for,
)
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"
FORMS = [form.name for form in FASHION_FIT_BODIES]


@pytest.fixture(scope="module", params=FORMS)
def form(request):
    chosen = next(f for f in FASHION_FIT_BODIES if f.name == request.param)
    document = GltfDocument.from_bytes(build_fit_form(chosen))
    return chosen, document


def test_every_form_is_declared_adult_by_the_repository_policy():
    for name in FORMS:
        assert declared_adult(name), name


def test_the_forms_are_not_calibration_bodies():
    """Four test modules and the gallery hashes iterate CALIBRATION_BODIES: the forms stay out of it."""
    assert not set(FORMS) & {body.name for body in CALIBRATION_BODIES}


def test_a_form_is_a_valid_vrm_at_its_declared_height(form):
    chosen, document = form
    info = inspect_document(document)
    measurements = measure_body(document, info)
    assert measurements.height_m == pytest.approx(chosen.height, abs=0.002)
    for side in ("left", "right"):  # feet and toes: a stocking foot has something to fit
        assert f"{side}Toes" in info.humanoid_bones
    mesh = build_fit_form_mesh(chosen, positions_for(chosen))
    assert not mesh.validate()


def test_a_tape_round_the_form_reads_the_chart(form):
    chosen, _ = form
    positions = positions_for(chosen)
    marks = form_landmarks(chosen, positions)
    torso = _torso(chosen, marks, 1.0).positions.astype(np.float64)
    for landmark, girth in chart(chosen).items():
        section = torso[np.abs(torso[:, 1] - marks[landmark]) < 0.007]
        measured = convex_girth(section[:, [0, 2]])
        assert measured == pytest.approx(girth, abs=0.012), (landmark, measured, girth)


def test_the_form_has_no_detail_smaller_than_two_centimetres(form):
    """Curvature radius between neighbouring vertices: no feature under ~20 mm across above the crotch.

    The only tight curve anywhere is the pole of the cap that closes the trunk
    between the thighs, below the crotch, where nothing is modelled but a closure.
    """
    chosen, _ = form
    marks = form_landmarks(chosen, positions_for(chosen))
    mesh = _torso(chosen, marks, 1.0)
    points, normals = mesh.positions.astype(np.float64), mesh.normals.astype(np.float64)
    tris = mesh.indices.reshape(-1, 3)
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    above = (points[edges[:, 0], 1] > marks["crotch"]) & (points[edges[:, 1], 1] > marks["crotch"])
    length = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    turn = np.arccos(np.clip((normals[edges[:, 0]] * normals[edges[:, 1]]).sum(axis=1), -1.0, 1.0))
    keep = above & (length > 1e-5)
    radius = length[keep] / np.maximum(turn[keep], 1e-9)
    assert radius.min() >= 0.010
    assert np.percentile(radius, 1) >= 0.025


def test_landmarks_are_measured_on_a_form(form):
    chosen, document = form
    marks = landmarks_for_document(document)
    assert marks is not None and not marks.warnings
    assert all(source == "measured" for source in marks.sources.values()), marks.sources
    declared = form_landmarks(chosen, positions_for(chosen))
    assert marks.waist_y == pytest.approx(declared["waist"], abs=0.04)
    assert marks.crotch_y == pytest.approx(declared["crotch"], abs=0.04)
    assert marks.crotch_y < marks.full_hip_y < marks.high_hip_y < marks.waist_y
    left, right = marks.bust_points["left"], marks.bust_points["right"]
    assert 0.6 * chosen.bust_span <= left[0] - right[0] <= 1.1 * chosen.bust_span
    assert abs(left[1] - declared["bust"]) < 0.03 and abs(left[0] + right[0]) < 0.005  # level, symmetric
    for side, fold in marks.underbust_y.items():
        assert marks.waist_y < fold < marks.bust_points[side][1]
    assert marks.bust_projection_m >= chosen.bust_projection * 0.6
    # The sternum lies between the bust points, behind them: that dip is the cleavage a gore sits in.
    assert marks.sternum[2] < min(left[2], right[2])


def test_a_calibration_body_has_formula_bust_points_and_says_so():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[2]))
    marks = landmarks_for_document(document)
    assert marks.sources["bustPoints"] == "formula" and marks.sources["underbust"] == "formula"
    assert any("no bust" in warning for warning in marks.warnings)
    assert marks.sources["waist"] == marks.sources["crotch"] == "measured"


@pytest.mark.parametrize("avatar", ["AvatarSample_A", "AvatarSample_B", "AvatarSample_C", "fem_vroid"])
def test_landmarks_on_the_library_avatars(avatar):
    path = LIBRARY / f"{avatar}.vrm"
    if not path.exists():
        pytest.skip("library avatars not fetched (make library)")
    marks = landmarks_for_document(GltfDocument.from_bytes(path.read_bytes()))
    assert marks is not None
    assert marks.crotch_y < marks.full_hip_y < marks.waist_y
    left, right = marks.bust_points["left"], marks.bust_points["right"]
    assert left[0] > marks.centre_x > right[0]
    assert all(marks.waist_y < fold < max(left[1], right[1]) + 1e-6 for fold in marks.underbust_y.values())
    # Measured or formula, never silently: a formula bust always says why.
    if marks.sources["bustPoints"] == "formula":
        assert marks.warnings
