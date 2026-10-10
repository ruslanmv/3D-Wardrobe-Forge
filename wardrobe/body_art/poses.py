"""BA3. The poses a tattoo is judged in: the hosiery poses, two of the stress tests, and arms raised.

``POSE_TESTS`` (wardrobe.engines.geometry_checks) has no raised-arm pose, and raised arms
are what move the shoulder blades under an upper-back tattoo. It is added here rather than
to ``POSE_TESTS``, which feeds every fit report: adding a pose there would change every
report ever compared against (the reason ``hosiery/poses.py`` gives for leaving it alone).
"""

from __future__ import annotations

import numpy as np

from wardrobe.engines.geometry_checks import POSE_TESTS
from wardrobe.hosiery import poses as hosiery_poses

#: ``arms-down`` mirrored: the upper arms lifted 60° above level.
ARMS_RAISED = {"leftUpperArm": (0.0, 0.0, 60.0), "rightUpperArm": (0.0, 0.0, -60.0)}

#: Name -> a hosiery pose name (facing-aware legs) or a rotation table.
POSES: dict[str, str | dict] = {
    "stand": "stand",
    "walk": "walk",
    "sit": "sit",
    "arms-down": POSE_TESTS["arms-down"],
    "legs-apart": POSE_TESTS["legs-apart"],
    "arms-raised": ARMS_RAISED,
}


def node_matrices(document, info, measurements, pose: str, forward: float) -> dict[int, np.ndarray]:
    """World transform per node in ``pose``."""
    pivots = {k: np.asarray(v, dtype=np.float64) for k, v in measurements.bone_positions.items()}
    return hosiery_poses.node_table(document, info, POSES[pose], forward, pivots)


def skin_points(
    points: np.ndarray, joints: np.ndarray, weights: np.ndarray, joint_nodes: np.ndarray, table: dict
) -> np.ndarray:
    """Linear blend skinning of rest-pose ``points``; ``joints`` index ``joint_nodes``."""
    matrices = np.stack([table.get(int(j), np.eye(4)) for j in joint_nodes])
    joints = np.clip(np.asarray(joints, dtype=np.int64), 0, len(matrices) - 1)
    blended = np.einsum("nk,nkij->nij", np.asarray(weights, dtype=np.float64), matrices[joints])
    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
    return np.einsum("nij,nj->ni", blended, homogeneous)[:, :3]


__all__ = ["ARMS_RAISED", "POSES", "node_matrices", "skin_points"]
