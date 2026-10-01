"""L4: the bra block — cups on her bust points, a gore on her sternum, a level band, straps from the cups.

The haul bra bridged straight across between her breasts with peaks at a fixed
angle. These hold the block to where a bra's pieces go, on the bodies the
repository declares adult: each bust point inside its cup, well clear of the
edges; the gore lying on her sternum; the band level under the fold; the straps
sewn to the anchors the cups publish; left and right the same; and the
construction — one bra body with two openings (band edge, top edge) and two
separate straps.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie.blocks.bra import COVER, COVER_MIN_M
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.seams import boundary_loops, components
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form

STYLES = ("triangle", "balconette", "plunge", "full")


@pytest.fixture(scope="module", params=[f.name for f in FASHION_FIT_BODIES])
def measured(request):
    assert declared_adult(request.param)
    form = next(f for f in FASHION_FIT_BODIES if f.name == request.param)
    return measure_document(GltfDocument.from_bytes(build_fit_form(form)))


def _bra(measured, **bra):
    meta = {**measured.metadata, "lingerie": {"block": "bra", "bra": bra}}
    return build_garment("bra-block", FitParameters(measurements=measured.measurements, metadata=meta,
                                                     clearance_m=0.0025))


def _neckline_above_apex(mesh, cup) -> float:
    top = mesh.positions[cup["rows"][-1]].astype(np.float64)
    order = np.argsort(top[:, 0])
    return float(np.interp(cup["apex"][0], top[order, 0], top[order, 1])) - cup["apex"][1]


@pytest.mark.parametrize("style", STYLES)
def test_a_bra_is_one_body_and_two_straps(measured, style):
    mesh = _bra(measured, style=style)
    assert not mesh.validate()
    assert components(mesh) == 3  # the band-and-cups, and a strap each side
    assert len(boundary_loops(mesh)) == 2  # the band's lower edge and one top edge; straps are closed
    assert set(mesh.metadata["lingerieBra"]["straps"]) == {"left", "right"}


@pytest.mark.parametrize("style", STYLES)
def test_each_bust_point_is_inside_its_cup(measured, style):
    mesh = _bra(measured, style=style)
    for cup in mesh.metadata["lingerieBra"]["cups"].values():
        apex_x = cup["apex"][0]
        assert abs(apex_x - cup["xIn"]) >= 0.015 and abs(cup["xOut"] - apex_x) >= 0.015
        above = _neckline_above_apex(mesh, cup)
        need = 0.015 if style == "triangle" else COVER.get(style, COVER_MIN_M) - 0.001
        assert above >= need, (style, above)


def test_the_gore_lies_on_her_sternum(measured):
    mesh = _bra(measured, style="balconette")
    record = mesh.metadata["lingerieBra"]
    marks = measured.landmarks
    top = np.asarray(record["bandRows"][-1][: record["frontColumns"]])
    gore = mesh.positions[top].astype(np.float64)
    middle = gore[np.argmin(np.abs(gore[:, 0] - marks.centre_x))]
    body = measured.points
    distance = float(np.min(np.linalg.norm(body - middle, axis=1)))
    assert distance <= 0.0025 + 0.003  # clearance, and 3 mm
    # And it is the dip between the bust points, not a bridge across them.
    apex_z = min(p[2] * marks.forward for p in marks.bust_points.values())
    assert middle[2] * marks.forward < apex_z


def test_the_band_is_level_under_the_fold(measured):
    mesh = _bra(measured, style="full")
    record = mesh.metadata["lingerieBra"]
    bottom = mesh.positions[np.asarray(record["bandRows"][0][:-1])].astype(np.float64)
    assert np.ptp(bottom[:, 1]) < 0.010
    assert record["bandBottom"] < record["fold"] <= min(measured.landmarks.underbust_y.values()) + 1e-9


def test_the_straps_are_sewn_to_the_cups_anchors(measured):
    mesh = _bra(measured, style="triangle")
    record = mesh.metadata["lingerieBra"]
    for side, strap in record["straps"].items():
        anchor = np.asarray(record["anchors"][side]["position"])
        assert np.linalg.norm(np.asarray(strap["front"]["position"]) - anchor) < 0.003
        assert strap["front"]["source"] == "cup" and strap["back"]["source"] == "band"
        assert strap["widthMm"] == pytest.approx(10.0) and strap["thicknessMm"] <= 1.5


def test_left_and_right_are_the_same(measured):
    mesh = _bra(measured, style="balconette")
    cups = mesh.metadata["lingerieBra"]["cups"]
    left, right = cups["left"], cups["right"]
    centre = measured.landmarks.centre_x
    assert abs(abs(left["xIn"] - centre) - abs(right["xIn"] - centre)) < 0.005
    assert abs(abs(left["xOut"] - centre) - abs(right["xOut"] - centre)) < 0.005
    assert abs(_neckline_above_apex(mesh, left) - _neckline_above_apex(mesh, right)) < 0.005
