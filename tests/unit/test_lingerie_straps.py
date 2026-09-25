"""L2: straps are flat ribbons between two published anchors, with a rest length and a worn one.

The haul bra's straps were round cords 7 mm thick whose ends were wherever a
formula put the top edge. These hold the replacement to the numbers a strap is
bought to: its cross-section, its ends on its anchors to the millimetre, and a
length at rest and worn, and keep it off her body.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wardrobe.geometry import ribbon as ribbon_module
from wardrobe.geometry.procedural import FitParameters
from wardrobe.hosiery import suspender_straps
from wardrobe.lingerie.contract import ElasticSpec, StrapSpec
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.specs import parse_block, validate_block
from wardrobe.lingerie.straps import anchor_on, build_ribbon_strap
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"


def _measured(data: bytes):
    measured = measure_document(GltfDocument.from_bytes(data))
    return measured, FitParameters(measurements=measured.measurements, metadata=measured.metadata)


@pytest.fixture(scope="module", params=[f.name for f in FASHION_FIT_BODIES] + ["AvatarSample_A"])
def body(request):
    if request.param == "AvatarSample_A":
        path = LIBRARY / "AvatarSample_A.vrm"
        if not path.exists():
            pytest.skip("library avatars not fetched (make library)")
        return _measured(path.read_bytes())
    form = next(f for f in FASHION_FIT_BODIES if f.name == request.param)
    return _measured(build_fit_form(form))


def _straps(measured, params, spec=None):
    marks = measured.landmarks
    out = []
    for side in ("left", "right"):
        ax, ay, _ = marks.bust_points[side]
        front = anchor_on(params, "cup-peak", side, ax, ay + 0.05, "front", source="test", lift=0.0015)
        back = anchor_on(params, "wing-top", side, ax * 0.9, marks.underbust_y[side] + 0.05, "back",
                         source="test", lift=0.0015)
        assert front is not None and back is not None
        built = build_ribbon_strap(params, front, back, spec=spec)
        assert built is not None
        out.append((front, back, *built))
    return out


def test_the_ribbon_moved_without_changing():
    """Suspenders import it from where it lived: the same function, so their straps did not move."""
    assert suspender_straps.ribbon is ribbon_module.ribbon
    assert suspender_straps.taut_length is ribbon_module.taut_length


def test_a_strap_is_flat_at_its_specified_section(body):
    measured, params = body
    spec = StrapSpec(width_m=0.012, thickness_m=0.0011)
    for _front, _back, mesh, _strap in _straps(measured, params, spec):
        corners = mesh.positions.astype(np.float64)[: 4 * (mesh.vertex_count // 4)].reshape(-1, 4, 3)
        width = np.linalg.norm(corners[:, 1] - corners[:, 0], axis=1)
        thickness = np.linalg.norm(corners[:, 2] - corners[:, 1], axis=1)
        assert np.allclose(width, 0.012, atol=0.0005)
        assert thickness.max() <= 0.0015 and np.allclose(thickness, 0.0011, atol=1e-4)


def test_a_strap_ends_on_its_anchors(body):
    measured, params = body
    for front, back, _mesh, strap in _straps(measured, params):
        assert np.linalg.norm(strap.path[0] - front.position) < 0.002
        assert np.linalg.norm(strap.path[-1] - back.position) < 0.002
        assert strap.front is front and strap.back is back


def test_a_strap_has_a_rest_length_and_a_worn_one(body):
    measured, params = body
    for _front, _back, mesh, strap in _straps(measured, params):
        worn = strap.current["stand"]
        assert 0.2 < worn < 0.6  # cup peak over the shoulder to the back band
        assert strap.rest_length < worn
        assert strap.stretch["stand"] == pytest.approx(StrapSpec().worn_stretch, abs=1e-6)
        assert strap.status("stand") == "ok"
        record = mesh.metadata["lingerieStrap"]
        assert record["restLengthM"] == pytest.approx(strap.rest_length, abs=1e-4)


def test_a_strap_stays_off_her_body(body):
    measured, params = body
    points = measured.points
    for _front, _back, mesh, _strap in _straps(measured, params):
        strap = mesh.positions.astype(np.float64)
        lo, hi = strap.min(axis=0) - 0.05, strap.max(axis=0) + 0.05
        near = points[np.all((points >= lo) & (points <= hi), axis=1)]
        distance = np.min(np.linalg.norm(strap[:, None, :] - near[None, :, :], axis=2), axis=1)
        assert distance.min() >= 0.0005


def test_an_elastic_pulls_harder_the_further_it_is_stretched():
    elastic = ElasticSpec("test", 10.0, ((0.0, 0.0), (0.1, 2.0), (0.3, 7.0)), cut_ratio=0.9)
    assert elastic.force(-0.05) == 0.0
    assert elastic.force(0.05) == pytest.approx(1.0)
    assert elastic.force(0.1) < elastic.force(0.2) < elastic.force(0.3) < elastic.force(0.4)


def test_the_template_lingerie_block_is_validated():
    assert not validate_block("bra-block", {"block": "bra", "straps": {"widthMm": 12}})
    assert validate_block("bra-block", {"block": "brief"})  # wrong block for the kind
    assert validate_block("brief-block", {"brief": {"backCoverage": "tiny"}})
    assert validate_block("bra-block", {"straps": {"profile": "cord"}})  # round cords are not built
    assert validate_block("bra-block", {"straps": {"widthMm": 10, "colour": "red"}})  # unknown field
    spec = parse_block("bra-block", {"straps": {"widthMm": 8, "thicknessMm": 1.0}}).straps.strap_spec()
    assert (spec.width_m, spec.thickness_m) == (0.008, 0.001)
