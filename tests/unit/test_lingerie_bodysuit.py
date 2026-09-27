"""L5: the bodysuit block — a brief carried up to a neckline, straps over her shoulders.

The one-piece swimsuit and the bodysuit were the haul's lofted band: a tube from
chest to hips. These hold the block to what a one-piece is, on the bodies the
repository declares adult: one body with three openings (neckline and two legs)
and two straps; its legs cut exactly as the brief of the same spec; its neckline
where the style puts it; its straps the same both sides; its upper panels placed
(the radial passes met her arms there, L4).
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.seams import boundary_loops, components
from wardrobe.lingerie.specs import validate_block
from wardrobe.lingerie.surface import PIT_M, _fill_pits
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form
from wardrobe.vrm.garments import KIND_REGIONS


@pytest.fixture(scope="module", params=[f.name for f in FASHION_FIT_BODIES])
def measured(request):
    assert declared_adult(request.param)
    form = next(f for f in FASHION_FIT_BODIES if f.name == request.param)
    return measure_document(GltfDocument.from_bytes(build_fit_form(form)))


def _build(measured, kind, **lingerie):
    meta = {**measured.metadata, "lingerie": lingerie}
    return build_garment(kind, FitParameters(measurements=measured.measurements, metadata=meta,
                                             clearance_m=0.0025))


def _bodysuit(measured, neckline="scoop", back="scoop", preset="cheeky"):
    return _build(measured, "bodysuit-block", block="bodysuit", brief={"preset": preset},
                  bodysuit={"neckline": neckline, "back": back})


def test_a_bodysuit_is_one_body_with_three_openings_and_two_straps(measured):
    mesh = _bodysuit(measured)
    assert not mesh.validate()
    assert components(mesh) == 3  # the body, and a strap each side
    assert len(boundary_loops(mesh)) == 3  # the neckline and two leg openings; straps are closed
    assert set(mesh.metadata["lingerieBodysuit"]["straps"]) == {"left", "right"}


@pytest.mark.parametrize("preset", ["cheeky", "high-leg", "thong"])
def test_its_legs_are_cut_exactly_as_the_brief_of_the_same_spec(measured, preset):
    """The leg line is solved against the brief's waistline, not the neckline."""
    brief = _build(measured, "brief-block", block="brief", brief={"preset": preset})
    body = _bodysuit(measured, preset=preset)
    want, got = brief.metadata["lingerieBrief"]["measures"], body.metadata["lingerieBrief"]["measures"]
    for key in ("frontCoverage", "backCoverage", "sideWidthMm", "legCutHeight"):
        assert got[key] == pytest.approx(want[key], abs=1e-6), key


def test_the_neckline_is_where_its_style_puts_it(measured):
    fronts = {n: _bodysuit(measured, neckline=n).metadata["lingerieBodysuit"]["heights"]
              for n in ("high", "scoop", "plunge")}
    assert fronts["plunge"]["front"] < fronts["scoop"]["front"] < fronts["high"]["front"]
    h = fronts["scoop"]
    assert h["strap"] > h["apex"] > h["fold"]  # the straps are sewn above her bust points
    assert h["fold"] < h["armhole"] < h["strap"]  # the armhole dips below the straps, not to her waist
    low = _bodysuit(measured, back="low").metadata["lingerieBodysuit"]["heights"]
    assert low["back"] < h["back"] < low["backStrap"]


@pytest.mark.parametrize("neckline", ["scoop", "plunge"])
def test_the_straps_are_the_same_both_sides(measured, neckline):
    """On one side of a form a hole in the depth map made one strap dive and hook (L5)."""
    anchors = _bodysuit(measured, neckline=neckline).metadata["lingerieBodysuit"]["anchors"]
    for face in ("front", "back"):
        left, right = (np.array(anchors[s][face]["position"]) for s in ("left", "right"))
        assert abs(left[0] + right[0]) < 0.002 and abs(left[1] - right[1]) < 0.002
        assert abs(left[2] - right[2]) < 0.002


def test_the_upper_panels_are_placed_and_the_lower_are_fitted(measured):
    mesh = _bodysuit(measured)
    record, heights = mesh.metadata["lingerieBrief"], mesh.metadata["lingerieBodysuit"]["heights"]
    panel = (int(record["rows"]) + 1) * int(record["columns"])
    placed = np.asarray(mesh.metadata["placed"])[:panel]
    y = mesh.positions[:panel, 1]
    assert placed[y > heights["fold"] + 0.001].all()
    below = (y < heights["fold"] - 0.01) & (y > record["heights"]["crotch"] + 0.05)
    assert not placed[below].any()


def test_the_templates_and_the_words_for_them():
    catalog = TemplateCatalog.from_directory("assets/garment_templates")
    assert "bodysuit-block" in LINGERIE_KINDS and KIND_REGIONS["bodysuit-block"] == {"upper", "lower"}
    for template_id in ("swim-one-piece-v2", "under-bodysuit-v2"):
        template = catalog.get(template_id)
        assert template.procedural_kind == "bodysuit-block"
        assert not validate_block("bodysuit-block", template.lingerie)
    from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

    for prompt, want in (("black one-piece swimsuit", "swim-one-piece-v2"), ("red swimsuit", "swim-one-piece-v2"),
                         ("black lace bodysuit", "under-bodysuit-v2"), ("black monokini", "swim-one-piece-v1")):
        assert plan_outfit_stack(OutfitRequest(prompt=prompt), catalog).template_id == want, prompt


def test_a_hole_in_the_depth_map_is_filled_and_her_cleavage_is_not():
    grid = np.full((7, 7), 0.10)
    grid[3, 3] = 0.01  # a hole: deeper than all four neighbours by 9 cm
    grid[3, 1:6] -= PIT_M * 0.6  # a groove across her: the cells above and below are as deep
    grid[2, 5] = grid[4, 5] = grid[3, 5]
    filled = _fill_pits(grid, "front")
    assert filled[3, 3] > 0.08
    assert np.allclose(np.delete(filled.ravel(), 3 * 7 + 3), np.delete(grid.ravel(), 3 * 7 + 3))


def test_a_high_leg_word_cuts_a_plain_bodysuit_high(measured):
    plain = _build(measured, "bodysuit-block", block="bodysuit", brief={"preset": "cheeky"})
    meta = {**measured.metadata, "legCut": "high", "lingerie": {"block": "bodysuit", "brief": {"preset": "cheeky"}}}
    high = build_garment("bodysuit-block", FitParameters(measurements=measured.measurements, metadata=meta,
                                                          clearance_m=0.0025))
    cut = [m.metadata["lingerieBrief"]["measures"]["legCutHeight"] for m in (plain, high)]
    from wardrobe.lingerie.specs import BOTTOM_PRESETS

    assert cut[1] == pytest.approx(BOTTOM_PRESETS["high-leg"]["legCutHeight"]) and cut[1] > cut[0]
    # A named cut keeps its own: a thong bodysuit is not made high-leg by the word.
    thong = {**meta, "lingerie": {"block": "bodysuit", "brief": {"preset": "thong"}}}
    kept = build_garment("bodysuit-block", FitParameters(measurements=measured.measurements, metadata=thong,
                                                          clearance_m=0.0025))
    assert kept.metadata["lingerieBrief"]["spec"]["preset"] == "thong"
