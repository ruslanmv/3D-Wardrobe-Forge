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
    ("a-line", 1.25, 1.42), ("fit-and-flare", 1.38, 1.58), ("pencil", 0.88, 1.0), ("sheath", 0.95, 1.05),
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
