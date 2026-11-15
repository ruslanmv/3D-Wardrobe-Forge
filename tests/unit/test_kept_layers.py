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

from wardrobe.geometry.kept_layers import INSIDE_TOP_M, MIN_SKIN_CLEARANCE_M, tuck_under_kept_tops
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


@pytest.mark.parametrize("category", ["dress", "top", "jacket", "underwear", "shoes", None])
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
