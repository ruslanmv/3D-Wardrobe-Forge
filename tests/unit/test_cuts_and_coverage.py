"""Coverage, cuts and strap networks: what the style layer does to geometry."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.garments import COVERAGE_PRESETS
from wardrobe.geometry.procedural import (
    COVERAGE_SCALE,
    MIN_SPAN_M,
    FitParameters,
    build_garment,
    front_angle,
)
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body


@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def build(measurements, kind: str, *, hem: str = "mini", sleeve: str = "none", **style):
    params = FitParameters(measurements=measurements, metadata=dict(style), sleeve_length=sleeve)
    return params, build_garment(kind, params, silhouette="slim", hem=hem)


def height_at(mesh, params, angle: float, width: float = 0.25) -> float:
    """Vertical extent of the garment's vertices near one direction round her body."""
    phi = front_angle(mesh.positions.astype(np.float64), params)
    near = np.abs((phi - angle + np.pi) % (2 * np.pi) - np.pi) < width
    y = mesh.positions[near, 1]
    return float(y.max() - y.min())


def top_at(mesh, params, angle: float, width: float = 0.2) -> float:
    phi = front_angle(mesh.positions.astype(np.float64), params)
    near = np.abs((phi - angle + np.pi) % (2 * np.pi) - np.pi) < width
    return float(mesh.positions[near, 1].max())


def test_coverage_scales_agree_across_layers():
    assert COVERAGE_SCALE == COVERAGE_PRESETS


def test_micro_briefs_are_a_string_at_the_sides_and_a_panel_at_the_front(measurements):
    params, standard = build(measurements, "briefs")
    _, micro = build(measurements, "briefs", coverage="micro")
    side = np.pi / 2
    assert height_at(micro, params, side) < height_at(standard, params, side) * 0.4
    assert height_at(micro, params, side) >= MIN_SPAN_M * 0.9  # never collapses
    assert height_at(micro, params, 0.0, width=0.1) > height_at(micro, params, side) * 2


def test_a_high_cut_leg_rises_at_the_hip(measurements):
    params, plain = build(measurements, "one-piece")
    _, high = build(measurements, "one-piece", legCut="high")
    side = np.pi / 2

    def bottom_at(mesh, angle):
        phi = front_angle(mesh.positions.astype(np.float64), params)
        near = np.abs((phi - angle + np.pi) % (2 * np.pi) - np.pi) < 0.2
        return float(mesh.positions[near, 1].min())

    assert bottom_at(high, side) > bottom_at(plain, side) + 0.03
    assert bottom_at(high, 0.0) == pytest.approx(bottom_at(plain, 0.0), abs=0.01)


def test_triangle_cups_peak_over_each_breast_and_dip_between(measurements):
    params, bra = build(measurements, "bra", neckline="triangle")
    cup, centre, back = top_at(bra, params, 0.42), top_at(bra, params, 0.0, 0.05), top_at(bra, params, np.pi)
    assert cup > centre + 0.01 and cup > back + 0.02


@pytest.mark.parametrize(("style", "angle", "deeper"), [("v", 0.0, True), ("plunge", 0.0, True)])
def test_necklines_cut_down_at_the_front_only(measurements, style, angle, deeper):
    params, plain = build(measurements, "dress")
    _, cut = build(measurements, "dress", neckline=style)
    assert top_at(cut, params, 0.0, 0.1) < top_at(plain, params, 0.0, 0.1) - 0.03
    assert top_at(cut, params, np.pi) == pytest.approx(top_at(plain, params, np.pi), abs=0.005)


def test_a_low_back_cuts_down_at_the_back_only(measurements):
    params, plain = build(measurements, "slip-dress", hem="midi")
    _, low = build(measurements, "slip-dress", hem="midi", back="low")
    assert top_at(low, params, np.pi) < top_at(plain, params, np.pi) - 0.05
    assert top_at(low, params, 0.0) == pytest.approx(top_at(plain, params, 0.0), abs=0.005)


def test_micro_shortens_a_skirt_but_not_past_the_crotch(measurements):
    params, standard = build(measurements, "skirt")
    _, micro = build(measurements, "skirt", coverage="micro")
    hem_standard, hem_micro = standard.positions[:, 1].min(), micro.positions[:, 1].min()
    assert hem_micro > hem_standard + 0.02
    thigh = params.hip_y - params.knee_y
    assert hem_micro <= params.hip_y - thigh * 0.19


def pieces(mesh) -> int:
    from wardrobe.vrm.skinning import connected_components

    return len(np.unique(connected_components(mesh)))


def test_strap_networks_add_their_pieces(measurements):
    _, plain = build(measurements, "bikini")
    _, string = build(measurements, "bikini", straps="string")
    _, garter = build(measurements, "briefs", straps="garter")
    _, harness = build(measurements, "bra", straps="harness")
    _, briefs = build(measurements, "briefs")
    assert pieces(string) == pieces(plain) + 2  # a tie at each hip
    assert pieces(garter) == pieces(briefs) + 5  # a belt and four suspenders
    assert pieces(harness) > pieces(build(measurements, "bra")[1]) + 2


def test_a_halter_ties_behind_her_neck_whichever_way_she_faces(measurements):
    """VRM 0.x faces -Z. A halter built toward +Z tied at her front and ran down her back."""
    import dataclasses

    from wardrobe.geometry.procedural import build_straps

    no_toes = dataclasses.replace(
        measurements, bone_positions={k: v for k, v in measurements.bone_positions.items() if "Toes" not in k}
    )
    for forward in (1.0, -1.0):
        params = FitParameters(measurements=no_toes, metadata={"forward": forward})
        assert params.forward == forward
        (strap, _) = build_straps(params, top_y=params.chest_y, style="halter")
        low = strap.positions[strap.positions[:, 1] < params.chest_y + 0.01]
        high = strap.positions[strap.positions[:, 1] > params.neck_y - 0.005]
        assert np.sign(low[:, 2].mean()) == forward  # on her bust
        assert np.sign(high[:, 2].mean()) == -forward  # tied behind her neck


def test_a_catsuit_runs_from_the_chest_to_the_ankles_with_sleeves(measurements):
    params, catsuit = build(measurements, "catsuit", sleeve="long")
    assert catsuit.positions[:, 1].min() < params.knee_y - (params.knee_y - params.ankle_y) * 0.7
    assert catsuit.positions[:, 1].max() > params.chest_y
    assert np.abs(catsuit.positions[:, 0]).max() > measurements.shoulder_width_m  # the sleeves


@pytest.mark.parametrize("cup", ["demi", "balconette"])
def test_demi_and_balconette_cups_are_cut_lower_at_the_front(measurements, cup):
    params, full = build(measurements, "bra")
    _, cut = build(measurements, "bra", neckline=cup)
    assert top_at(cut, params, 0.0, 0.3) < top_at(full, params, 0.0, 0.3) - 0.005
    assert top_at(cut, params, np.pi) == pytest.approx(top_at(full, params, np.pi), abs=0.003)


def test_rise_moves_the_waistband(measurements):
    params, standard = build(measurements, "briefs")
    _, high = build(measurements, "briefs", rise="high")
    _, low = build(measurements, "briefs", rise="low")
    top = lambda mesh: mesh.positions[:, 1].max()  # noqa: E731
    assert top(high) > top(standard) > top(low)


def test_trim_sections_are_marked_for_their_own_material(measurements):
    from wardrobe.geometry.procedural import trim_triangles

    _, bra = build(measurements, "bra", straps="harness")
    mask = trim_triangles(bra)
    assert mask.any() and not mask.all()
    _, briefs = build(measurements, "briefs")
    edges = trim_triangles(briefs)
    assert edges.any() and not edges.all()  # waistband and leg openings are elastic; the panel is not
    _, stocking = build(measurements, "legwear")
    band = trim_triangles(stocking)
    assert band.any() and band.mean() < 0.5  # a top band on each leg, not the whole stocking
    _, dress = build(measurements, "dress")
    assert not trim_triangles(dress).any()
