"""PF2. A second-skin garment's weights are diffused over its own surface between her legs.

Synthetic strips stand in for a brief's panel: a grid in x (across her) and y (down her),
with each vertex's left/right thigh share set by hand. What the smoothing must do — and not
do — is checked on numbers, without a body: a step becomes a slope, the slope stays where the
step was, nothing moves above her hip band or down by her knee, a seam's two copies of a
vertex end with the same weights, and every row still sums to one.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.weight_transfer import (
    HIP_BAND_M,
    SMOOTH_FADE_BELOW_M,
    smooth_below_hips,
)

HIP_Y = 0.89


def strip(y0: float, y1: float, x0: float = -0.06, x1: float = 0.06, step: float = 0.005) -> Mesh:
    xs = np.arange(x0, x1 + 1e-9, step)
    ys = np.arange(y0, y1 + 1e-9, step)
    grid = np.array([(x, y, 0.1) for y in ys for x in xs], dtype=np.float32)
    nx = xs.size
    tris = []
    for j in range(ys.size - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1
            tris += [(a, b, c), (b, d, c)]
    return Mesh(positions=grid, indices=np.asarray(tris, dtype=np.uint32).ravel())


def stepped(mesh: Mesh) -> np.ndarray:
    """Columns: hips, left thigh, right thigh. Left of x=0 all left thigh, right of it all right."""
    left = (mesh.positions[:, 0] < 0).astype(np.float64)
    return np.stack([np.zeros_like(left), left, 1.0 - left], axis=1)


def test_a_step_between_her_thighs_becomes_a_slope():
    mesh = strip(HIP_Y - 0.12, HIP_Y - 0.05)
    dense = stepped(mesh)
    smoothed = smooth_below_hips(mesh, dense, hip_y=HIP_Y)
    x = mesh.positions[:, 0]
    across = np.abs(np.diff(smoothed[np.argsort(x), 1]))
    assert across.max() < 0.5  # the hand-set step was 1.0 between neighbours
    # The slope is centred where the step was, and far from it each side keeps its own thigh.
    assert np.all(smoothed[x < -0.05, 1] > 0.85) and np.all(smoothed[x > 0.05, 2] > 0.85)
    np.testing.assert_allclose(smoothed.sum(axis=1), 1.0, atol=1e-9)


def test_above_her_hip_band_and_by_her_knee_nothing_moves():
    high = strip(HIP_Y + HIP_BAND_M + 0.005, HIP_Y + HIP_BAND_M + 0.04)
    np.testing.assert_array_equal(smooth_below_hips(high, stepped(high), hip_y=HIP_Y), stepped(high))
    knee = strip(HIP_Y - SMOOTH_FADE_BELOW_M - 0.2, HIP_Y - SMOOTH_FADE_BELOW_M - 0.01)
    np.testing.assert_array_equal(smooth_below_hips(knee, stepped(knee), hip_y=HIP_Y), stepped(knee))


def test_uniform_weights_are_left_as_they_were():
    mesh = strip(HIP_Y - 0.12, HIP_Y - 0.05)
    dense = np.tile([0.2, 0.8, 0.0], (mesh.positions.shape[0], 1))
    np.testing.assert_allclose(smooth_below_hips(mesh, dense, hip_y=HIP_Y), dense, atol=1e-12)


def test_a_seams_two_copies_of_a_vertex_end_with_one_set_of_weights():
    left, right = strip(HIP_Y - 0.1, HIP_Y - 0.05, -0.06, 0.0), strip(HIP_Y - 0.1, HIP_Y - 0.05, 0.0, 0.06)
    count = left.positions.shape[0]
    mesh = Mesh(
        positions=np.vstack([left.positions, right.positions]),
        indices=np.concatenate([left.indices, right.indices + count]),
    )
    dense = stepped(mesh)
    dense[:count] = [0.0, 1.0, 0.0]  # the left panel all left thigh, its seam column included
    smoothed = smooth_below_hips(mesh, dense, hip_y=HIP_Y)
    on_seam = np.flatnonzero(np.abs(mesh.positions[:, 0]) < 1e-6)
    by_height = {}
    for v in on_seam:
        by_height.setdefault(round(float(mesh.positions[v, 1]), 4), []).append(smoothed[v])
    pairs = [w for w in by_height.values() if len(w) == 2]
    assert pairs
    for a, b in pairs:
        np.testing.assert_allclose(a, b, atol=1e-12)
