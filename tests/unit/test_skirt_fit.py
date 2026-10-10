"""Skirts cut from her measured waist and hips, then flared: the silhouette, held to numbers.

A skirt used to be every ring the hip width times a flare, only its top ring her
real width: it stepped out from her waist and ran as a straight cone to a hem
55–70% wider than her hips. These tests pin the shape that replaced it, so a
regression cannot quietly turn the skirts back into bells.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.garments import GarmentTemplate
from wardrobe.engines.geometry_checks import (
    BodyRadialIndex,
    apply_drape,
    apply_pleats,
    body_points,
    lower_body_profile,
    torso_profile,
)
from wardrobe.geometry.procedural import (
    SKIRT_SHAPES,
    FitParameters,
    _full_hip_y,
    build_garment,
    build_skirt,
    crotch_y,
    skirt_shape,
)
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body


@pytest.fixture(scope="module", params=[b.name for b in CALIBRATION_BODIES])
def measured(request):
    """A calibration body with the metadata fitting gives a skirt: her outline and her legs."""
    body = next(b for b in CALIBRATION_BODIES if b.name == request.param)
    document = GltfDocument.from_bytes(build_vrm(body, spec="VRM1"))
    measurements = measure_body(document, inspect_document(document))
    points = body_points(document)
    bones = measurements.bone_positions
    legs = points[(points[:, 1] < bones["leftUpperLeg"][1]) & (np.abs(points[:, 0]) > 0.01)]
    metadata = {}
    lower = lower_body_profile(points, legs, bones)
    if lower is not None:
        metadata["lowerBody"] = lower
    arms = np.abs(points[:, 0]) > abs(bones["leftUpperArm"][0]) * 0.95
    profile = torso_profile(points[~arms], bones["chest"][1], bones["leftLowerLeg"][1])
    assert profile is not None
    metadata["torsoProfile"] = profile
    return measurements, metadata, points


def _widths(mesh):
    """Half-width per ring, top first."""
    heights = np.round(mesh.positions[:, 1].astype(np.float64), 4)
    ys = np.unique(heights)[::-1]
    return ys, np.array([np.ptp(mesh.positions[heights == y][:, 0]) / 2 for y in ys])


def _params(measured, **metadata):
    measurements, meta, _ = measured
    return FitParameters(measurements=measurements, metadata={**meta, **metadata})


@pytest.mark.parametrize(("silhouette", "low", "high"), [
    ("a-line", 1.25, 1.42), ("fit-and-flare", 1.38, 1.58), ("pencil", 0.86, 0.92), ("sheath", 0.95, 1.05),
])
def test_the_hem_is_the_silhouettes_ratio_of_her_full_hip(measured, silhouette, low, high):
    params = _params(measured)
    shape = skirt_shape(params, silhouette, 1.0)
    hem_y = params.hip_y - (params.hip_y - params.ankle_y) * 0.62
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=hem_y, shape=shape)
    ys, widths = _widths(mesh)
    hip = widths[np.argmin(np.abs(ys - _full_hip_y(params)))]
    assert low <= widths[-1] / hip <= high, (silhouette, widths[-1] / hip)


def test_a_skirt_is_fitted_at_the_waist_not_a_scaled_hip(measured):
    params = _params(measured)
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.knee_y,
                       shape=skirt_shape(params, "a-line", 1.55))
    ys, widths = _widths(mesh)
    hip = widths[np.argmin(np.abs(ys - _full_hip_y(params)))]
    assert widths[0] < hip  # her waist goes in
    assert widths[0] < hip * 0.95 or widths[0] - hip < 0.004  # never a cylinder from the hip up
    # Below the full hip it only widens: it hangs from her hips, never back in round her thighs.
    below = widths[ys < _full_hip_y(params)]
    assert np.all(np.diff(below) >= -1e-4)


def test_the_flare_is_progressive(measured):
    """Power above 1: half-way down the flare, well under half of it has arrived."""
    params = _params(measured)
    shape = skirt_shape(params, "a-line", 1.55)
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.knee_y, shape=shape)
    ys, widths = _widths(mesh)
    start = _full_hip_y(params)
    hip = widths[np.argmin(np.abs(ys - start))]
    middle = widths[np.argmin(np.abs(ys - (start + params.knee_y) / 2))]
    assert (middle - hip) / (widths[-1] - hip) < 0.5 ** shape.flare_power + 0.08


def test_the_full_hip_is_found_above_her_crotch(measured):
    params = _params(measured)
    assert _full_hip_y(params) > crotch_y(params, params.hip_y)
    assert _full_hip_y(params) <= params.waist_y


def test_template_fields_override_the_silhouette():
    params = FitParameters(measurements=None, metadata={"hemFlareRatio": 1.2, "flarePower": 2.0,
                                                        "flareStart": "waist"})
    shape = skirt_shape(params, "a-line", 1.55)
    assert (shape.hem_ratio, shape.flare_power, shape.flare_start) == (1.2, 2.0, "waist")
    assert skirt_shape(FitParameters(measurements=None), "a-line", 1.55) == SKIRT_SHAPES["a-line"]


def test_the_old_flare_multipliers_are_gone_from_skirts(measured, template_catalog):
    """No skirt template's hem may exceed 1.9x her full hip (the old A-line reached 1.55 on a cone)."""
    params = _params(measured)
    for template in template_catalog.all():
        if template.procedural_kind != "skirt":
            continue
        fit = template.fit
        extra = {k: v for k, v in (("hemFlareRatio", fit.hem_flare_ratio), ("flarePower", fit.flare_power),
                                   ("flareStart", fit.flare_start)) if v is not None}
        p = FitParameters(measurements=params.measurements, metadata={**params.metadata, **extra})
        mesh = build_garment("skirt", p, silhouette=template.silhouette, hem=template.hem)
        ys, widths = _widths(mesh)
        hip = widths[np.argmin(np.abs(ys - _full_hip_y(p)))]
        assert widths.max() / hip < 1.9, template.id


# ----------------------------------------------------------------------
# pleats and drape: zero-mean, never inside her
# ----------------------------------------------------------------------
def _fitted_skirt(measured, shape="a-line"):
    measurements, meta, points = measured
    params = FitParameters(measurements=measurements, metadata=meta, segments=96)
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.hip_y - 0.2,
                       shape=skirt_shape(params, shape, 1.55))
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    return params, mesh, index


def _ring_radii(mesh, index, y):
    heights = np.round(mesh.positions[:, 1].astype(np.float64), 4)
    ring = heights == heights[np.argmin(np.abs(heights - y))]
    return np.hypot(mesh.positions[ring, 0] - index.axis_x, mesh.positions[ring, 2] - index.axis_z)


def test_pleats_fold_both_ways_around_the_cut(measured):
    params, mesh, index = _fitted_skirt(measured)
    hem = float(mesh.positions[:, 1].min())
    before = _ring_radii(mesh, index, hem).copy()
    apply_pleats(mesh, index, count=16, from_y=params.waist_y - 0.03, amplitude=0.04, clearance_m=0.006,
                 retexture=True)
    after = _ring_radii(mesh, index, hem)
    change = after / before - 1.0
    assert change.max() > 0.03 and change.min() < -0.03  # in and out, not a bell
    assert abs(change.mean()) < 0.006  # the same size as the cut
    assert mesh.metadata.get("pleatShading")
    assert np.ptp(mesh.uvs[:, 0]) == pytest.approx(16, abs=0.05)  # u in pleats, for the shading


def test_pleats_never_fold_into_her(measured):
    params, mesh, index = _fitted_skirt(measured, shape="pencil")
    apply_pleats(mesh, index, count=16, from_y=params.waist_y - 0.03, amplitude=0.08, clearance_m=0.006)
    points = mesh.positions.astype(np.float64)
    inside = index.point_radius(points) < index.body_radius_at(points)
    assert not inside[index.body_radius_at(points) > 0.009].any()


def test_a_draped_hem_is_zero_mean_and_opens_toward_the_hem(measured):
    params, mesh, index = _fitted_skirt(measured, shape="fit-and-flare")
    hem = float(mesh.positions[:, 1].min())
    top_before = _ring_radii(mesh, index, params.waist_y).copy()
    before = _ring_radii(mesh, index, hem).copy()
    apply_drape(mesh, index, folds=8, from_y=params.hip_y, amplitude=0.05, clearance_m=0.006)
    change = _ring_radii(mesh, index, hem) / before - 1.0
    assert change.max() > 0.03 and abs(change.mean()) < 0.006
    assert np.allclose(_ring_radii(mesh, index, params.waist_y), top_before)  # nothing moves above the hips


def test_an_unknown_flare_start_is_invalid(template_catalog):
    good = template_catalog.get("skirt-a-line-v1")
    broken = GarmentTemplate.model_validate({**good.model_dump(by_alias=True),
                                             "fit": {**good.fit.model_dump(by_alias=True), "flareStart": "knee"}})
    assert any("flareStart" in issue for issue in broken.validate_semantics())
    assert not good.validate_semantics()


# ----------------------------------------------------------------------
# S4. the pleated mini: one width of pleat all round, set under a real band
# ----------------------------------------------------------------------
def _pleated_mini(measured, **extra):
    """The pleated mini's own cut and columns, built the way fitting builds it."""
    measurements, meta, points = measured
    params = FitParameters(measurements=measurements, metadata={
        **meta, "pleats": 24, "waistbandMm": 38.0, "hemFlareRatio": 1.22, "flareStart": "hip",
        "flarePower": 1.35, **extra}, segments=24 * 8)
    mesh = build_garment("skirt", params, silhouette="a-line", hem="mini")
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    return params, mesh, index


def _rings(mesh, segments):
    return mesh.positions.astype(np.float64).reshape(-1, segments + 1, 3)


def test_even_columns_are_one_length_of_fabric_apart(measured):
    """Equal angles round her made the front pleats 40% wider than the side ones."""
    _, mesh, _ = _pleated_mini(measured)
    for ring in _rings(mesh, 24 * 8)[::4]:
        steps = np.linalg.norm(np.diff(ring[:, [0, 2]], axis=0), axis=1)
        assert steps.std() / steps.mean() < 0.01


def test_the_band_and_the_pleat_line_are_rows_of_their_own(measured):
    from wardrobe.geometry.procedural import PLEAT_SET_M, skirt_top

    params, mesh, _ = _pleated_mini(measured)
    rows = np.unique(np.round(mesh.positions[:, 1].astype(np.float64), 4))
    top = skirt_top(params)
    for line in (top - 0.038, top - 0.038 - PLEAT_SET_M):
        assert np.abs(rows - line).min() < 2e-4
    # Nothing a hair away from them: no sliver rows to shade badly.
    assert np.diff(rows).min() > 0.004


def test_every_fold_runs_down_one_column(measured):
    """Float noise put the fold one column left on some rows and right on others: a zig-zag edge."""
    from wardrobe.geometry.procedural import PLEAT_SET_M, skirt_top

    params, mesh, index = _pleated_mini(measured)
    apply_pleats(mesh, index, count=24, from_y=skirt_top(params) - 0.038 - PLEAT_SET_M + 1e-4, amplitude=0.022,
                 clearance_m=0.006, retexture=True)
    rings = _rings(mesh, 24 * 8)
    radii = np.hypot(rings[..., 0] - index.axis_x, rings[..., 2] - index.axis_z)
    hem = float(mesh.positions[:, 1].min())
    lower = rings[:, 0, 1] < hem + (params.hip_y - hem) * 0.5
    steps = np.diff(radii, axis=1) / radii[:, :-1]  # relative: her sides are nearer the axis than her front
    folds = [tuple(np.flatnonzero(r < -0.5 * np.abs(r).max())) for r in steps[lower]]
    assert len(set(folds)) == 1  # the same columns on every row: a straight pressed edge
    # On the pleat grid, eight columns a pleat; a fold clearance softened near her legs may
    # fall under the threshold, never off the grid.
    assert len(folds[0]) >= 20 and all(column % 8 == 7 for column in folds[0])


def test_pleats_stay_zero_mean_at_any_column_count(measured):
    params, mesh, index = _pleated_mini(measured)
    hem = float(mesh.positions[:, 1].min())
    before = _ring_radii(mesh, index, hem).copy()
    apply_pleats(mesh, index, count=24, from_y=params.waist_y - 0.05, amplitude=0.022, clearance_m=0.006)
    change = _ring_radii(mesh, index, hem) / before - 1.0
    assert abs(change.mean()) < 0.002 and change.max() > 0.015


def test_the_pleated_mini_is_fitted_through_the_hip_then_gently_flared(measured, template_catalog):
    template = template_catalog.get("skirt-pleated-mini-v1")
    fit = template.fit
    assert fit.flare_start == "hip" and 1.15 <= fit.hem_flare_ratio <= 1.3 and fit.pleats >= 20
    assert 30.0 <= fit.waistband_mm <= 45.0
    params, mesh, _ = _pleated_mini(measured)
    ys, widths = _widths(mesh)
    hip = widths[np.argmin(np.abs(ys - _full_hip_y(params)))]
    assert 1.12 <= widths[-1] / hip <= 1.3  # was 1.6: a lampshade
    # No flare above the full hip: from the band down to it the skirt follows her.
    above = (ys > _full_hip_y(params)) & (ys < params.waist_y - 0.04)
    assert np.all(widths[above] <= hip + 0.004)


# ----------------------------------------------------------------------
# S5. knife pleats with real folds; a front kept flat; a mini that is a mini
# ----------------------------------------------------------------------
def _knife(measured, **extra):
    from wardrobe.engines.geometry_checks import apply_knife_pleats, pleat_phase
    from wardrobe.geometry.procedural import PLEAT_SET_M, skirt_top

    measurements, meta, points = measured
    params = FitParameters(measurements=measurements, metadata={
        **meta, "pleats": 24, "waistbandMm": 38.0, "hemFlareRatio": 1.2, "flareStart": "hip",
        "flarePower": 1.35, **extra}, segments=24 * 12)
    mesh = build_garment("skirt", params, silhouette="a-line", hem="mini")
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    before = mesh.positions.astype(np.float64).copy()
    phase = pleat_phase(mesh, 24)
    origin = apply_knife_pleats(mesh, index, count=24, from_y=skirt_top(params) - 0.038 - PLEAT_SET_M + 1e-4,
                                step=0.022, clearance_m=0.006, retexture=True)
    return params, mesh, index, before, phase, origin


def _hem_ring(mesh, origin, before, phase):
    """The hem row after folding: positions, each vertex's place in its pleat, and its unfolded radius."""
    points = mesh.positions.astype(np.float64)
    hem = points[:, 1] < points[:, 1].min() + 1e-4
    s = phase[origin] - np.floor(phase[origin] + 1e-3)
    radius = np.hypot(points[:, 0], points[:, 2])
    was = np.hypot(before[origin, 0], before[origin, 2])
    return hem, np.clip(s, 0.0, 1.0), radius, was


def test_a_knife_pleat_has_a_face_a_fold_edge_and_an_underfold(measured):
    from wardrobe.engines.geometry_checks import KNIFE_UNDERLAP

    _, mesh, _, before, phase, origin = _knife(measured)
    assert origin is not None and mesh.vertex_count > before.shape[0]  # the creases split the fold edges
    hem, s, radius, _ = _hem_ring(mesh, origin, before, phase)
    face = 1.0 / (1.0 + 2.0 * KNIFE_UNDERLAP)
    edge = hem & (s < 1e-3)
    face_end = hem & (s > face * 0.8) & (s < face)
    under = hem & (s >= face) & (s < face + KNIFE_UNDERLAP * face)
    # The fold edge stands over the face it covers, and the underfold lies under both.
    assert radius[edge].mean() > radius[face_end].mean() > radius[under].mean() - 1e-4
    assert radius[edge].mean() - radius[under].mean() > 0.002


def test_knife_pleats_keep_the_size_of_the_cut(measured):
    _, mesh, _, before, phase, origin = _knife(measured)
    hem, s, radius, was = _hem_ring(mesh, origin, before, phase)
    visible = hem & (s < 1.0 / 1.7)
    assert abs(radius[visible].mean() / was[visible].mean() - 1.0) < 0.015


def test_every_knife_pleat_is_built_the_same(measured):
    """Same pleat, same width, same depth all round: the front, the side and the back match."""
    _, mesh, _, before, phase, origin = _knife(measured)
    hem, s, radius, _ = _hem_ring(mesh, origin, before, phase)
    # Against the unfolded ring at each vertex's new angle: the fold slides it along an ellipse.
    points = mesh.positions.astype(np.float64)
    ring = before[before[:, 1] < before[:, 1].min() + 1e-4]
    ring_angle = np.arctan2(ring[:, 0], ring[:, 2])
    order = np.argsort(ring_angle)
    unfolded = np.interp(np.arctan2(points[:, 0], points[:, 2]), ring_angle[order],
                         np.hypot(ring[order, 0], ring[order, 2]), period=2 * np.pi)
    relative = radius / unfolded - 1.0
    pleat = np.floor(phase[origin] + 1e-3).astype(int) % 24
    for lo, hi in ((0.0, 1e-3), (0.2, 0.3), (0.65, 0.75)):
        member = hem & (s >= lo) & (s < hi)
        per_pleat = [relative[member & (pleat == p)].mean() for p in range(24) if (member & (pleat == p)).any()]
        assert len(per_pleat) == 24 and np.std(per_pleat) < 0.004


def test_knife_pleats_never_fold_into_her(measured):
    _, mesh, index, *_ = _knife(measured)
    points = mesh.positions.astype(np.float64)
    reach = index.body_radius_at(points)
    inside = index.point_radius(points) < reach + 0.006 - 1e-4
    assert not inside[reach > 0.009].any()


def test_a_fitted_pleated_skirt_keeps_its_front_flat_and_its_seat_behind(measured):
    params = _params(measured)
    even = skirt_shape(params, "a-line", 1.0)
    from dataclasses import replace

    shaped = replace(even, hem_ratio=1.2, front_flare=0.45, back_flare=1.0)
    plain = replace(even, hem_ratio=1.2)
    hem_y = params.hip_y - (params.hip_y - params.ankle_y) * 0.22
    front = params.forward

    def growth(shape):
        mesh = build_skirt(params, y_top=params.waist_y, y_bottom=hem_y, shape=shape)
        z = mesh.positions[:, 2].astype(np.float64) * front
        ys = np.round(mesh.positions[:, 1].astype(np.float64), 4)
        hip, hem = ys == ys[np.argmin(np.abs(ys - _full_hip_y(params)))], ys == ys.min()
        return z[hem].max() - z[hip].max(), z[hip].min() - z[hem].min()

    front_grows, back_grows = growth(shaped)
    assert front_grows < back_grows * 0.6  # the front stays nearly flat; the back carries the flare
    plain_front, plain_back = growth(plain)
    assert abs(plain_front - plain_back) < 0.004  # without the fields, the even flare it always had


def test_a_mini_ends_on_the_upper_thigh_and_clears_the_crotch(measured):
    from wardrobe.geometry.procedural import MINI_HEM_FRACTION

    params = _params(measured)
    mesh = build_garment("skirt", params, silhouette="a-line", hem="mini")
    hem = float(mesh.positions[:, 1].min())
    crotch = crotch_y(params, params.hip_y)
    assert MINI_HEM_FRACTION <= 0.25
    assert hem < crotch - 0.03  # covers her
    assert hem > params.knee_y + (params.hip_y - params.knee_y) * 0.4  # and is a mini: well above the knee


# ----------------------------------------------------------------------
# S6. tight over the hip, pleats closed there and open at the hem
# ----------------------------------------------------------------------
def test_pleats_are_closed_over_the_hip_and_open_at_the_hem(measured):
    from wardrobe.engines.geometry_checks import apply_knife_pleats, pleat_phase
    from wardrobe.geometry.procedural import PLEAT_SET_M, full_hip_y, skirt_top

    measurements, meta, points = measured
    params = FitParameters(measurements=measurements, metadata={
        **meta, "pleats": 24, "waistbandMm": 38.0, "hemFlareRatio": 1.19, "flareStart": "hip",
        "flarePower": 1.8}, segments=24 * 12)
    mesh = build_garment("skirt", params, silhouette="a-line", hem="mini")
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    phase = pleat_phase(mesh, 24)
    top = skirt_top(params) - 0.038 - PLEAT_SET_M + 1e-4
    hem = float(mesh.positions[:, 1].min())
    hip = min(full_hip_y(params), top - 0.01)
    opening = [(top, 0.0), ((top + hip) / 2, 0.15), (hip, 0.30), ((hip + hem) / 2, 0.68), (hem, 1.0)]
    origin = apply_knife_pleats(mesh, index, count=24, from_y=top, step=0.04, opening=opening,
                                clearance_m=0.0)
    p = mesh.positions.astype(np.float64)
    s = phase[origin] - np.floor(phase[origin] + 1e-3)
    rows = np.round(p[:, 1], 4)

    def fold_depth(y):
        row = rows == rows[np.argmin(np.abs(rows - y))]
        r = np.hypot(p[:, 0], p[:, 2])
        edge, under = row & (s < 1e-3), row & (s > 0.62) & (s < 0.78)
        return r[edge].mean() - r[under].mean()

    assert fold_depth(hip) < 0.5 * fold_depth(hem)  # pressed over the hip, open at the hem


def test_a_taut_column_never_moves_in_and_spans_a_hollow(measured):
    from wardrobe.engines.geometry_checks import taut_columns

    params = _params(measured)
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.hip_y - 0.1, shape=skirt_shape(params, "a-line", 1.0))
    _, _, points = measured
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    p = mesh.positions.astype(np.float64)
    rows = np.unique(np.round(p[:, 1], 4))
    dent = np.abs(np.round(p[:, 1], 4) - rows[len(rows) // 2]) < 1e-4
    p[dent, 0] *= 0.97  # a hollow in one row
    p[dent, 2] *= 0.97
    mesh.positions = p.astype(np.float32)
    before = np.hypot(p[:, 0] - index.axis_x, p[:, 2] - index.axis_z)
    taut_columns(mesh, index, top=float(rows.max()), bottom=float(rows.min()), round_m=0.02)
    q = mesh.positions.astype(np.float64)
    after = np.hypot(q[:, 0] - index.axis_x, q[:, 2] - index.axis_z)
    assert (after >= before - 1e-6).all()  # never closer to her
    assert (after[dent] / before[dent]).mean() > 1.02  # the hollow is spanned


def test_rounding_a_bend_never_goes_below_it():
    from wardrobe.engines.geometry_checks import _rounded_profile

    y = np.linspace(0.0, 0.2, 15)
    r = np.where(y < 0.1, 0.16, 0.16 + (y - 0.1) * 0.2)  # a corner at y = 0.1
    out = _rounded_profile(y, r, 0.02)
    assert (out >= r - 1e-9).all()
    assert np.abs(np.diff(out, 2)).max() < np.abs(np.diff(r, 2)).max()  # the corner is softer
    assert out[0] - r[0] < 0.001 and out[-1] - r[-1] < 0.001  # and the ends stay put


def test_conforming_fades_out_above_its_floor(measured):
    from wardrobe.engines.geometry_checks import conform_to_body

    params = _params(measured)
    _, _, points = measured
    mesh = build_skirt(params, y_top=params.waist_y, y_bottom=params.knee_y, shape=skirt_shape(params, "a-line", 1.0))
    index = BodyRadialIndex(points, y_range=(float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max())))
    before = mesh.positions.astype(np.float64).copy()
    floor = params.hip_y
    conform_to_body(mesh, index, 0.005, strength=1.0, min_y=floor, fade_m=0.03)
    moved = np.linalg.norm(mesh.positions.astype(np.float64) - before, axis=1)
    y = np.round(before[:, 1], 4)
    rows = np.unique(y[(y >= floor) & (y < floor + 0.03)])
    full = max(float(moved[y > floor + 0.03].max()), 1e-6)
    for row in rows:  # inside the fade each row moves no more than its eased share
        t = (row - floor) / 0.03
        assert moved[y == row].max() <= (t * t * (3 - 2 * t) + 0.05) * full + 1e-6


def test_the_pleated_mini_is_cut_tight_over_the_hip(template_catalog):
    fit = template_catalog.get("skirt-pleated-mini-v1").fit
    assert fit.conform_to == "full-hip" and fit.conform >= 0.9
    assert (fit.waist_ease_mm or 0.0) <= 1.0 and (fit.hip_ease_mm or 0.0) <= 3.0
    assert 1.18 <= fit.hem_flare_ratio <= 1.20 and fit.flare_power >= 1.6
    assert fit.front_flare < fit.back_flare <= 1.0
