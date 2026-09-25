"""The bottom-pattern grammar: every style a preset over independent rules, held to numbers.

"String" is how the sides are made, "thong" how much back there is, "high-leg"
the leg opening's height, "bikini" a rise-and-coverage family. Modelled as four
meshes, a string bikini (string sides, a real back) could only be a thong. These
tests read each pattern's own measurements (``lingerieBrief.measures``) and hold
the styles apart where they are commonly confused, on the bodies the repository
declares adult.
"""

from __future__ import annotations

import pytest

from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.seams import boundary_loops, components
from wardrobe.lingerie.specs import BOTTOM_PRESETS, BriefSpec, parse_block
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form


@pytest.fixture(scope="module", params=[f.name for f in FASHION_FIT_BODIES])
def measured(request):
    assert declared_adult(request.param)
    form = next(f for f in FASHION_FIT_BODIES if f.name == request.param)
    return measure_document(GltfDocument.from_bytes(build_fit_form(form)))


def _build(measured, brief: dict):
    meta = {**measured.metadata, "lingerie": {"block": "brief", "brief": brief}}
    return build_garment("brief-block", FitParameters(measurements=measured.measurements, metadata=meta,
                                                      clearance_m=0.0025))


@pytest.fixture(scope="module")
def styles(measured):
    return {name: _build(measured, {"preset": name}) for name in BOTTOM_PRESETS}


def _m(styles, name):
    return styles[name].metadata["lingerieBrief"]["measures"]


def test_every_preset_is_one_brief_with_three_openings(styles):
    for name, mesh in styles.items():
        ties = mesh.metadata["lingerieBrief"].get("ties") or 0
        assert components(mesh) == 1 + ties, name  # a tie's bow is sewn on, not cut from the panels
        assert len(boundary_loops(mesh)) == 3, name
        assert not mesh.validate(), name


def test_coverage_is_what_the_spec_asks_where_the_construction_allows(styles):
    """The leg line is solved: the measured coverage is the spec's, unless a narrower back cannot reach it."""
    for name in ("classic", "high-leg", "cheeky", "brazilian", "tanga", "bikini", "string-bikini", "hipster"):
        spec = parse_block("brief-block", {"brief": {"preset": name}}).brief
        m = _m(styles, name)
        assert m["backCoverage"] == pytest.approx(spec.back_fraction, abs=0.01), name
        assert m["frontCoverage"] == pytest.approx(spec.front_fraction, abs=0.01), name


def test_classic(styles):
    m = _m(styles, "classic")
    assert m["backCoverage"] > 0.75 and m["sideWidthMm"] > 35


def test_high_leg_is_cut_higher_and_keeps_its_back(styles):
    assert _m(styles, "high-leg")["legCutHeight"] > _m(styles, "classic")["legCutHeight"]
    assert _m(styles, "high-leg")["backCoverage"] > 0.65
    assert _m(styles, "french-cut")["legCutHeight"] > _m(styles, "classic")["legCutHeight"]
    assert _m(styles, "french-cut")["backCoverage"] > 0.75


def test_cheeky(styles):
    assert 0.45 < _m(styles, "cheeky")["backCoverage"] < 0.70


def test_brazilian_sits_between_cheeky_and_thong_with_a_v_back(styles):
    m = _m(styles, "brazilian")
    assert 0.25 < m["backCoverage"] < 0.50
    assert m["backVDepth"] > _m(styles, "cheeky")["backVDepth"]
    assert _m(styles, "thong")["backCoverage"] < m["backCoverage"] < _m(styles, "cheeky")["backCoverage"]


def test_tanga(styles):
    m = _m(styles, "tanga")
    assert m["sideWidthMm"] < 15 and 0.30 < m["backCoverage"] < 0.55


def test_thong(styles):
    assert _m(styles, "thong")["backCoverage"] < 0.20
    assert _m(styles, "high-waist-thong")["backCoverage"] < 0.20
    assert _m(styles, "high-waist-thong")["rise"] > _m(styles, "thong")["rise"]


def test_g_string_and_v_string(styles):
    for name in ("g-string", "v-string"):
        m = _m(styles, name)
        assert m["sideWidthMm"] < 10 and m["backCenterWidthMm"] < 8 and m["backCoverage"] < 0.10, name
    assert _m(styles, "v-string")["backVDepth"] > _m(styles, "g-string")["backVDepth"]


def test_a_string_bikini_is_not_a_thong(styles):
    """String sides, and still a back: the confusion this grammar exists to prevent."""
    bikini, thong = _m(styles, "string-bikini"), _m(styles, "thong")
    assert bikini["sideWidthMm"] < 10
    assert bikini["backCoverage"] > 0.50
    assert bikini["backCoverage"] - thong["backCoverage"] > 0.3
    assert styles["string-bikini"].metadata["lingerieBrief"]["ties"] > 0


def test_high_waist_hipster_and_boyshort(styles):
    assert _m(styles, "high-waist")["rise"] > 1.0 and _m(styles, "high-waist")["backCoverage"] > 0.85
    assert _m(styles, "hipster")["rise"] < _m(styles, "classic")["rise"]
    assert _m(styles, "hipster")["backCoverage"] > 0.85
    boyshort = styles["boyshort"].metadata["lingerieBrief"]
    assert boyshort["legExtension"] and boyshort["measures"]["backCoverage"] > 0.9
    # Its leg openings are below her crotch, round her thighs.
    for leg in boyshort["legExtension"]["legs"].values():
        last = styles["boyshort"].positions[leg["rings"][-1]]
        assert float(last[:, 1].max()) < boyshort["heights"]["crotch"]


def test_the_rules_are_orthogonal(measured):
    """Change one rule and only its measure moves."""
    base = {"rise": 0.7, "sideWidthMm": 40, "backCoverage": 0.6, "frontCoverage": 0.6}
    ref = _build(measured, base).metadata["lingerieBrief"]["measures"]
    sides = _build(measured, {**base, "sideWidthMm": 8}).metadata["lingerieBrief"]["measures"]
    back = _build(measured, {**base, "backCoverage": 0.42}).metadata["lingerieBrief"]["measures"]
    assert sides["sideWidthMm"] == pytest.approx(8, abs=0.5)
    assert sides["backCoverage"] == pytest.approx(ref["backCoverage"], abs=0.02)  # thinner sides, same back
    assert back["backCoverage"] == pytest.approx(0.42, abs=0.01)
    assert back["sideWidthMm"] == pytest.approx(ref["sideWidthMm"], abs=0.01)  # less back, same sides


def test_presets_are_overridable_and_validated():
    spec = parse_block("brief-block", {"brief": {"preset": "cheeky", "backCoverage": 0.5}}).brief
    assert isinstance(spec, BriefSpec) and spec.back_fraction == 0.5 and spec.side_width_mm == 38
    assert parse_block("brief-block", {"brief": {"preset": "nope"}}).issues
    assert parse_block("brief-block", {"brief": {"sideType": "rope"}}).issues
    assert parse_block("brief-block", {"brief": {"backCoverage": 1.4}}).issues
