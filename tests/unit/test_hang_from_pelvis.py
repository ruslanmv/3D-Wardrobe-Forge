"""A dress below the hip joint hangs from the pelvis, not from both thighs.

Sitting (Wide) rotates the thighs apart. A hem vertex bound to a thigh and its
neighbour bound to the hips become a long triangle: on the black bodycon that
edge ran from 15 mm to 66 mm. The bodice stays as bound. Weights still sum to one.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.skinning import BoneSegment, hang_from_pelvis

HIP_Y = 0.90


def _segment(name: str) -> BoneSegment:
    head = np.zeros(3)
    return BoneSegment(name=name, node=0, head=head, tail=head + np.array([0.0, -0.1, 0.0]))


def test_vertices_below_the_hip_give_their_leg_weight_to_the_hips():
    positions = np.array(
        [
            [0.00, 1.05, 0.05],  # bodice, already on the chest
            [0.00, 0.75, -0.09],  # crotch, split across the two thighs
            [-0.08, 0.80, -0.08],  # left hem, all on the left thigh
            [0.10, 0.95, 0.00],  # above the joint, keeps its thigh share
        ],
        dtype=np.float32,
    )
    mesh = Mesh(positions=positions, indices=np.array([0, 1, 2, 1, 2, 3], dtype=np.uint32))
    # slots: hips, left thigh, right thigh, chest
    mesh.joints = np.array(
        [
            [3, 0, 1, 2],
            [1, 2, 0, 3],
            [1, 0, 2, 3],
            [0, 1, 2, 3],
        ],
        dtype=np.uint16,
    )
    mesh.weights = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.5, 0.5, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.4, 0.6, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    segments = [_segment(name) for name in ("hips", "leftUpperLeg", "rightUpperLeg", "chest")]

    hang_from_pelvis(mesh, segments, hip_y=HIP_Y)

    def on(vertex: int, bone: int) -> float:
        return float(mesh.weights[vertex, mesh.joints[vertex] == bone].sum())

    assert np.allclose(mesh.weights.sum(axis=1), 1.0, atol=1e-5)
    # The bodice is above the joint.
    assert on(0, 3) == 1.0
    # Both thigh shares of the crotch vertex are now on the hips.
    assert on(1, 0) == 1.0
    assert on(1, 1) == 0.0 and on(1, 2) == 0.0
    # A hem vertex that was only a thigh is only the hips.
    assert on(2, 0) == 1.0 and on(2, 1) == 0.0
    # Above the joint the original thigh share is untouched.
    assert on(3, 1) == pytest.approx(0.6)


def test_without_a_pelvis_the_binding_is_left_alone():
    positions = np.array([[0.0, 0.5, 0.0]], dtype=np.float32)
    mesh = Mesh(positions=positions, indices=np.array([0, 0, 0], dtype=np.uint32))
    mesh.joints = np.array([[0, 0, 0, 0]], dtype=np.uint16)
    mesh.weights = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    before = mesh.weights.copy()
    hang_from_pelvis(mesh, [_segment("leftUpperLeg")], hip_y=HIP_Y)
    assert np.array_equal(mesh.weights, before)
