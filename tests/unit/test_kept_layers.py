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

from wardrobe.geometry import kept_layers
from wardrobe.geometry.kept_layers import (
    HEM_BAND_M,
    INSIDE_TOP_M,
    MAX_TAPER_M,
    MIN_SEPARATION_M,
    MIN_SKIN_CLEARANCE_M,
    REACH_M,
    TAPER_SLOPE,
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
    # Only inside the top's height span or the taper just under its hem (KL3), and only ever inwards.
    assert mesh.positions[moved, 1].min() >= report["keptTopHemY"] - REACH_M - 1e-6
    hips = measurements.bone_positions["hips"]
    r_before = np.hypot(before[moved, 0] - hips[0], before[moved, 2] - hips[2])
    r_after = np.hypot(mesh.positions[moved, 0] - hips[0], mesh.positions[moved, 2] - hips[2])
    assert np.all(r_after < r_before)
    # Heights are untouched: a tuck is radial.
    assert np.allclose(before[:, 1], mesh.positions[:, 1])
    assert INSIDE_TOP_M > 0 and MIN_SKIN_CLEARANCE_M > 0


def test_nothing_further_below_her_hem_than_the_taper_moves(her):
    """KL1: nothing below her hem moved, and the row under it stood 19 mm proud of the cardigan
    (the triangle up to its tucked neighbour cut through the hem). KL3 tapers that row in, for
    MAX_TAPER_M and no further."""
    doc, measurements = her
    mesh = tube(measurements, 0.25)
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    far = before[:, 1] < report["keptTopHemY"] - REACH_M
    assert far.any() and np.array_equal(before[far], mesh.positions[far])
    assert REACH_M <= MAX_TAPER_M + 0.025  # the taper, and the few cells its need is spread over
    assert report["tapered"] > 0 and report["version"] == 3


def _radius(points, measurements):
    hips = measurements.bone_positions["hips"]
    return np.hypot(points[:, 0] - hips[0], points[:, 2] - hips[2])


def test_under_her_hem_the_bottom_leaves_at_a_slope_not_a_step(her):
    """The taper: the further below her hem, the further out it may stand, never more than
    TAPER_SLOPE allows from the top's inner line, and back to its own radius by MAX_TAPER_M."""
    doc, measurements = her
    mesh = tube(measurements, 0.19)  # a few centimetres outside her top at the hips, as jeans are
    before = mesh.positions.copy()
    report = tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    after = _radius(mesh.positions, measurements)
    hem = report["keptTopHemY"]
    below = (before[:, 1] < hem) & (before[:, 1] >= hem - MAX_TAPER_M)
    moved = below & np.any(before != mesh.positions, axis=1)
    assert moved.any()
    # Row by row going down from her hem, the narrowest point only ever gets wider.
    heights = np.unique(before[below, 1])[::-1]
    narrowest = [after[before[:, 1] == y].min() for y in heights]
    assert all(b >= a - 1e-4 for a, b in zip(narrowest, narrowest[1:], strict=False))
    assert narrowest[-1] <= 0.19 + 1e-6 and narrowest[0] < 0.19 - 0.005
    # Never outwards, never a height changed, never a vertex more or fewer.
    assert np.all(after <= _radius(before, measurements) + 1e-6)
    assert np.allclose(before[:, 1], mesh.positions[:, 1]) and before.shape == mesh.positions.shape
    assert TAPER_SLOPE > 0


def test_where_there_is_no_room_the_bottom_still_goes_under_her_top(her):
    """KL3, the front-hem band. With a layer under it that fills the space to her top, KL1 found
    "no room" and left the vertex where the shell built it: outside the cardigan, drawn over its
    hem. It goes under the top now, as far in as with nothing under it (but for the margin an
    outer layer keeps), and is counted."""
    doc, measurements = her
    alone = tube(measurements, 0.25)
    before = alone.positions.copy()
    report_alone = tuck_under_kept_tops(doc, alone, measurements, category="trousers")
    over_briefs = tube(measurements, 0.25)
    briefs = tube(measurements, 0.24).positions  # fills everything out to just under the bottom
    report = tuck_under_kept_tops(doc, over_briefs, measurements, category="trousers", inner_points=briefs)
    assert report["noRoom"] == 0 and report["pressedUnderHem"] > 0 and report_alone["pressedUnderHem"] == 0
    hem = report["keptTopHemY"]
    band = (before[:, 1] >= hem) & (before[:, 1] < hem + HEM_BAND_M)
    tucked = band & np.any(before != alone.positions, axis=1)  # what her top covers there
    assert tucked.any()
    margin = INSIDE_TOP_M - kept_layers.OUTER_INSIDE_TOP_M
    ended = _radius(over_briefs.positions, measurements)[tucked]
    # As far in as with nothing under it, but for the margin; or, where there is room for both,
    # no further out than just over the layer under it. (1 mm: a neighbourhood moves together.)
    as_alone = _radius(alone.positions, measurements)[tucked] + margin
    over_the_layer = 0.24 + kept_layers.VISIBLE_OVER_INNER_M
    assert np.all(ended <= np.maximum(as_alone, over_the_layer) + 1e-3)
    assert np.any(ended < 0.24)  # pressed in past the layer under it, under her top


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
    # Where the bottom shows it is never inside the briefs. That is below her hem (KL3: in the
    # hem band her top covers it, and there it goes under the top even with no room; see
    # test_where_there_is_no_room_the_bottom_still_goes_under_her_top).
    shows = mesh.positions[:, 1] < report["keptTopHemY"]
    assert r[shows].min() >= 0.20 + MIN_SEPARATION_M - 1e-4
    assert report["moved"] > 0 and HEM_BAND_M > 0


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
            # 0.8 rad to each side: wider than the taper and its spread reach from the edges
            # (KL3), so the middle of the opening is beyond both.
            angle = np.arctan2(points[:, 2] - hips[2], points[:, 0] - hips[0])
            points = points[np.abs(angle - np.pi / 2) > 0.8]
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


def test_her_hem_is_found_where_it_hangs_not_at_its_lowest_point(her):
    """KL3. A cardigan's panels end lower at the front than its back does. With one hem for the
    whole top, the true hem band at her back was treated as hidden, and beside a panel the air
    was averaged in. Here the top is cut higher over half of her: on that side nothing her
    top no longer covers is treated as covered."""  # (the cut below is 15 cm, for whole tube rows)
    doc, measurements = her
    from wardrobe.engines.geometry_checks import body_points as real_points
    from wardrobe.geometry import kept_layers as kl

    hips = measurements.bone_positions["hips"]
    state = {"n": 0, "cut": None}

    def higher_at_one_side(document, **kw):
        points = real_points(document, **kw)
        state["n"] += 1
        if state["n"] == 1:  # the top: its hem 6 cm higher where x > her axis
            state["cut"] = float(points[:, 1].min()) + 0.15
            points = points[(points[:, 0] <= hips[0]) | (points[:, 1] >= state["cut"])]
        return points

    import wardrobe.engines.geometry_checks as gc
    original = gc.body_points
    gc.body_points = higher_at_one_side
    try:
        mesh = tube(measurements, 0.25)
        before = mesh.positions.copy()
        report = kl.tuck_under_kept_tops(doc, mesh, measurements, category="trousers")
    finally:
        gc.body_points = original
    # Well inside the raised half (clear of the cut's edge), below the raised hem by more than
    # the taper: untouched, although it is above the top's lowest point.
    raised = (before[:, 0] > hips[0] + 0.17) & (before[:, 1] < state["cut"] - REACH_M - 0.005)
    above_global_hem = raised & (before[:, 1] > report["keptTopHemY"])
    assert above_global_hem.any()
    assert np.array_equal(before[above_global_hem], mesh.positions[above_global_hem])
    # The other half is tucked at those same heights.
    low = (before[:, 0] < hips[0] - 0.17) & (before[:, 1] > report["keptTopHemY"] + 0.01) & (
        before[:, 1] < state["cut"] - REACH_M - 0.005)
    assert low.any() and np.any(before[low] != mesh.positions[low])


def test_a_seams_two_vertices_stay_in_one_place(her):
    """KL3. A seam is two vertices at one position. A floor is read per cell, and twins either
    side of a cell's edge were moved 1.8 mm apart (the waistband of AvatarSample C's shorts)."""
    doc, measurements = her
    once = tube(measurements, 0.19)
    twice = Mesh(positions=np.vstack([once.positions, once.positions + np.float32(4e-6)]),
                 indices=np.zeros(0, dtype=np.uint32))
    briefs = tube(measurements, 0.17).positions  # so that floors bind somewhere
    report = tuck_under_kept_tops(doc, twice, measurements, category="trousers", inner_points=briefs)
    assert report["moved"] > 0
    n = once.positions.shape[0]
    gap = np.linalg.norm(twice.positions[:n] - twice.positions[n:], axis=1)
    assert gap.max() < 2e-5
