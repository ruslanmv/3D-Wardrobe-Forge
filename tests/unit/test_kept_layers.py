"""KL1. A new bottom goes on under the top she keeps (the jeans hip split).

Seen on AvatarSample A with straight jeans: the jeans were fitted to her body alone and drawn
over her kept cardigan, whose ribbed hem then came through the denim all round her hips. Here
on AvatarSample O (the library's other character with a kept top), with a stand-in tube for the
bottom so the test measures the pass itself, not the shell builder.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wardrobe.geometry.kept_layers import (
    HEM_BAND_M,
    INSIDE_TOP_M,
    MIN_SEPARATION_M,
    MIN_SKIN_CLEARANCE_M,
    tuck_under_kept_tops,
)
from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

SAMPLE_O = Path(__file__).resolve().parents[2] / "assets/library/vroid/vroid-avatar-sample-o.vrm"


@pytest.fixture(scope="module")
def her():
    if not SAMPLE_O.exists():
        pytest.skip("library file not present")
    doc = GltfDocument.from_path(SAMPLE_O)
    return doc, measure_body(doc, inspect_document(doc))


def tube(measurements, radius: float) -> Mesh:
    hips = measurements.bone_positions["hips"]
    ys = np.linspace(hips[1] - 0.3, hips[1] + 0.25, 40)
    turns = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    points = [[hips[0] + radius * np.cos(t), y, hips[2] + radius * np.sin(t)] for y in ys for t in turns]
    return Mesh(positions=np.array(points, dtype=np.float32), indices=np.zeros(0, dtype=np.uint32))


def test_a_bottom_outside_her_top_is_moved_inside_it_and_never_into_her(her):
    doc, measurements = her
    mesh = tube(measurements, 0.25)  # well outside her top at the hips
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    assert report["moved"] > 0
    moved = np.any(before != mesh.positions, axis=1)
    # Only inside the top's height span, and only ever inwards.
    assert mesh.positions[moved, 1].min() >= report["keptTopHemY"] - 1e-6
    hips = measurements.bone_positions["hips"]
    r_before = np.hypot(before[moved, 0] - hips[0], before[moved, 2] - hips[2])
    r_after = np.hypot(mesh.positions[moved, 0] - hips[0], mesh.positions[moved, 2] - hips[2])
    assert np.all(r_after < r_before)
    # Heights are untouched: a tuck is radial.
    assert np.allclose(before[:, 1], mesh.positions[:, 1])
    assert INSIDE_TOP_M > 0 and MIN_SKIN_CLEARANCE_M > 0


def test_nothing_below_her_hem_moves(her):
    doc, measurements = her
    mesh = tube(measurements, 0.25)
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    below = before[:, 1] < report["keptTopHemY"]
    assert below.any() and np.array_equal(before[below], mesh.positions[below])


def test_a_bottom_already_inside_is_left_alone(her):
    doc, measurements = her
    mesh = tube(measurements, 0.02)  # inside everything: not this pass's business
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    assert report["moved"] == 0 and np.array_equal(before, mesh.positions)


@pytest.mark.parametrize("category", ["dress", "top", "jacket", "shoes", "legwear", None])
def test_only_bottoms_are_tucked(her, category):
    doc, measurements = her
    mesh = tube(measurements, 0.25)
    before = mesh.positions.copy()
    assert tuck_under_kept_tops(doc, mesh, measurements, category=category) is None
    assert np.array_equal(before, mesh.positions)


def test_no_kept_top_no_change(vrm_bytes):
    doc = GltfDocument.from_bytes(vrm_bytes)
    measurements = measure_body(doc, inspect_document(doc))
    assert tuck_under_kept_tops(doc, tube(measurements, 0.25), measurements, category="trousers") is None


def test_a_layer_already_fitted_under_it_is_a_floor_too(her):
    """Over the foundation briefs, the first KL1 pulled the jeans inside them (beige patches)."""
    doc, measurements = her
    hips = measurements.bone_positions["hips"]
    briefs = tube(measurements, 0.20).positions  # an inner layer just inside the bottom
    mesh = tube(measurements, 0.25)
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers", inner_points=briefs)
    r = np.hypot(mesh.positions[:, 0] - hips[0], mesh.positions[:, 2] - hips[2])
    # Where the bottom shows (below the hem and in the hem band) it is never inside the briefs.
    shows = mesh.positions[:, 1] < report["keptTopHemY"] + HEM_BAND_M
    assert r[shows].min() >= 0.20 + MIN_SEPARATION_M - 1e-4
    assert report["moved"] + report["noRoom"] > 0


def test_above_the_hem_band_it_is_only_inside_the_top(her):
    """Hidden by the top there: inside it, even where the top is closer to her than any floor."""
    doc, measurements = her
    mesh = tube(measurements, 0.25)
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    hips = measurements.bone_positions["hips"]
    hidden = (before[:, 1] >= report["keptTopHemY"] + HEM_BAND_M) & np.any(before != mesh.positions, axis=1)
    assert hidden.any()
    r = np.hypot(mesh.positions[hidden, 0] - hips[0], mesh.positions[hidden, 2] - hips[2])
    assert np.all(r < 0.25) and np.all(r > 0)


def test_underwear_under_a_kept_top_is_tucked_too(her):
    doc, measurements = her
    mesh = tube(measurements, 0.25)
    assert tuck_under_kept_tops(doc, mesh, measurements, category="underwear")["moved"] > 0


def test_where_the_top_is_open_nothing_is_tucked(her):
    """A cardigan's open front: no top in that sector, so the bottom there is left as fitted."""
    doc, measurements = her
    from wardrobe.engines.geometry_checks import body_points as real_points
    from wardrobe.geometry import kept_layers as kl

    hips = measurements.bone_positions["hips"]
    calls = {"n": 0}

    def without_front(document, **kw):
        points = real_points(document, **kw)
        calls["n"] += 1
        if calls["n"] == 1:  # the top: cut a wedge out of it, straight ahead of her
            angle = np.arctan2(points[:, 2] - hips[2], points[:, 0] - hips[0])
            points = points[np.abs(angle - np.pi / 2) > 0.5]
        return points

    import wardrobe.engines.geometry_checks as gc
    original = gc.body_points
    gc.body_points = without_front
    try:
        mesh = tube(measurements, 0.25)
        before = mesh.positions.copy()
        kl.tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    finally:
        gc.body_points = original
    angle = np.arctan2(before[:, 2] - hips[2], before[:, 0] - hips[0])
    opening = np.abs(angle - np.pi / 2) < 0.2
    assert np.array_equal(before[opening], mesh.positions[opening])


def test_a_foundation_in_the_tops_slot_is_not_a_kept_top(her):
    """KL2. A Forge bralette is filed under tops with the role "foundation". Read as a kept top,
    a waspie layered over it was pulled inside the bralette's band: up to 21 mm into her ribs at
    rest (the underwear audit). Nothing goes under a foundation."""
    import copy

    doc, measurements = her
    as_foundation = GltfDocument(copy.deepcopy(doc.gltf), doc.binary)
    for node in as_foundation.nodes:
        if "mesh" in node:
            node["extras"] = {"wardrobeForge": {"kind": "garment", "slot": "tops", "role": "foundation"}}
    mesh = tube(measurements, 0.25)
    before = mesh.positions.copy()
    assert tuck_under_kept_tops(as_foundation, mesh, measurements, category="underwear") is None
    assert np.array_equal(before, mesh.positions)
    # The same top as an outer layer (or her own) still is one.
    for node in as_foundation.nodes:
        if "mesh" in node:
            node["extras"]["wardrobeForge"]["role"] = "main"
    assert tuck_under_kept_tops(as_foundation, mesh, measurements, category="underwear")["moved"] > 0
