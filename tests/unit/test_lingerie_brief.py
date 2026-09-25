"""L3: the brief block is three pieces with three openings, drafted to its spec on her landmarks.

The haul brief was an open tube with its bottom edge lifted at the sides: two
openings, nothing under her, and every style the same geometry scaled. These
hold the block to what a brief is: one garment, exactly three openings (waist
and two legs), a gusset whose seams are the panels' own edge vertices; and to
the pattern-maker's numbers: rise, back rise, side height, and a back leg line
that climbs with less coverage. Built on the bodies the repository declares
adult, and only on those.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie.blocks.brief import GUSSET_COLUMNS, GUSSET_ROWS
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.seams import boundary_loops, components
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form

BODIES = [f.name for f in FASHION_FIT_BODIES] + ["calibration-c-tall"]
STYLES = {
    "classic": {},
    "high-leg": {"rise": 0.8, "sideHeight": 0.2, "frontScoop": 0.75, "backCoverage": "moderate"},
    "string": {"rise": 0.62, "sideHeight": 0.05, "backCoverage": "cheeky"},
    "thong": {"rise": 0.66, "sideHeight": 0.05, "backCoverage": "thong"},
}


@pytest.fixture(scope="module", params=BODIES)
def measured(request):
    assert declared_adult(request.param)
    if request.param.startswith("calibration"):
        data = build_vrm(next(b for b in CALIBRATION_BODIES if b.name == request.param))
    else:
        data = build_fit_form(next(f for f in FASHION_FIT_BODIES if f.name == request.param))
    return measure_document(GltfDocument.from_bytes(data))


def _brief(measured, **brief):
    meta = {**measured.metadata, "lingerie": {"block": "brief", "brief": brief}}
    params = FitParameters(measurements=measured.measurements, metadata=meta, clearance_m=0.0025)
    return build_garment("brief-block", params)


@pytest.mark.parametrize("style", sorted(STYLES))
def test_a_brief_is_one_garment_with_three_openings(measured, style):
    mesh = _brief(measured, **STYLES[style])
    assert not mesh.validate()
    assert components(mesh) == 1
    loops = boundary_loops(mesh)
    assert len(loops) == 3, [len(loop) for loop in loops]


def test_the_gusset_is_sewn_to_the_panels_edge_vertices(measured):
    mesh = _brief(measured)
    record = mesh.metadata["lingerieBrief"]
    grid = record["gusset"]
    assert len(grid) == GUSSET_ROWS + 2 and all(len(row) == GUSSET_COLUMNS + 1 for row in grid)
    panels_bottom = {record["rows"] * record["columns"] + j for j in range(record["columns"])}
    assert set(grid[0]) <= panels_bottom and set(grid[-1]) <= panels_bottom  # shared, not copied
    # The shell's radial passes leave exactly the gusset's interior; the seams are panel vertices.
    placed = np.flatnonzero(mesh.metadata["placed"])
    assert set(placed) == {v for row in grid[1:-1] for v in row}
    # Front seam, left to right; back seam, left to right: the rows join straight across.
    positions = mesh.positions.astype(np.float64)
    assert np.all(np.diff(positions[grid[0], 0]) > 0) and np.all(np.diff(positions[grid[-1], 0]) > 0)


def test_heights_are_the_specs_fractions_of_her_rise(measured):
    mesh = _brief(measured, rise=0.7, backRise=0.08, sideHeight=0.4)
    heights = mesh.metadata["lingerieBrief"]["heights"]
    span = heights["waist"] - heights["crotch"]
    assert heights["frontWaist"] == pytest.approx(heights["crotch"] + 0.7 * span, abs=1e-6)
    assert heights["backWaist"] - heights["frontWaist"] == pytest.approx(0.08 * span, abs=1e-6)
    record = mesh.metadata["lingerieBrief"]
    side = np.asarray(record["sideSeam"]["a"])
    ys = mesh.positions[side, 1].astype(np.float64)
    side_waist = (heights["frontWaist"] + heights["backWaist"]) / 2
    assert ys[0] == pytest.approx(side_waist, abs=0.004)
    assert ys[0] - ys[-1] == pytest.approx(0.4 * span, abs=0.005)  # the side panel, to 5 mm


def test_a_high_leg_is_cut_higher_at_the_side_not_scaled(measured):
    classic, high = _brief(measured), _brief(measured, **STYLES["high-leg"])
    side = {name: m.metadata["lingerieBrief"]["heights"]["sideBottom"] for name, m in
            (("classic", classic), ("high", high))}
    assert side["high"] > side["classic"] + 0.02
    # The gusset is the same construction, not a smaller copy: its seam height does not move.
    assert (classic.metadata["lingerieBrief"]["heights"]["seam"]
            == high.metadata["lingerieBrief"]["heights"]["seam"])


def test_less_back_coverage_is_a_higher_back_leg_line(measured):
    """At 150° round her (the lower seat), the leg line climbs full → moderate → cheeky → thong."""
    heights = []
    for coverage in ("full", "moderate", "cheeky", "thong"):
        mesh = _brief(measured, backCoverage=coverage)
        record = mesh.metadata["lingerieBrief"]
        bottom = mesh.positions[record["rows"] * record["columns"]:(record["rows"] + 1) * record["columns"]]
        bottom = bottom.astype(np.float64)
        marks = measured.landmarks
        angle = np.arctan2(bottom[:, 0] - marks.centre_x, (bottom[:, 2]) * marks.forward)
        at = np.argmin(np.abs(np.abs(angle) - math.radians(150)))
        heights.append(float(bottom[at, 1]))
    assert heights == sorted(heights) and heights[-1] - heights[0] > 0.03


def test_elastic_and_gusset_are_their_own_sections(measured):
    mesh = _brief(measured)
    names = [name for name, _first, count in mesh.metadata["sections"] if count]
    assert names == ["elastic-brief-waist", "brief", "elastic-brief-leg", "gusset"]
    assert sum(count for _n, _f, count in mesh.metadata["sections"]) == mesh.triangle_count
