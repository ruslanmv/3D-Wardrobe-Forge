"""Automatic skin-weight binding for generated garments.

The garment is authored in the avatar's own rest-pose world space, so binding
reduces to: for every vertex, find the nearest humanoid bone *segments* and
distribute weight between them. Restricting the candidate set to the template's
declared anchor bones is what stops a skirt from picking up the head bone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.measure import BodyMeasurements

MAX_INFLUENCES = 4

#: Parent -> preferred children, used to give each bone a direction (a "tail").
HUMANOID_CHILDREN: dict[str, tuple[str, ...]] = {
    "hips": ("spine",),
    "spine": ("chest", "upperChest", "neck"),
    "chest": ("upperChest", "neck"),
    "upperChest": ("neck",),
    "neck": ("head",),
    "head": (),
    "leftShoulder": ("leftUpperArm",),
    "leftUpperArm": ("leftLowerArm",),
    "leftLowerArm": ("leftHand",),
    "leftHand": (),
    "rightShoulder": ("rightUpperArm",),
    "rightUpperArm": ("rightLowerArm",),
    "rightLowerArm": ("rightHand",),
    "rightHand": (),
    "leftUpperLeg": ("leftLowerLeg",),
    "leftLowerLeg": ("leftFoot",),
    "leftFoot": ("leftToes",),
    "leftToes": (),
    "rightUpperLeg": ("rightLowerLeg",),
    "rightLowerLeg": ("rightFoot",),
    "rightFoot": ("rightToes",),
    "rightToes": (),
}

#: Which bones a garment covering a given body region should bind to.
COVERAGE_BONES: dict[str, tuple[str, ...]] = {
    "chest": ("chest", "upperChest", "spine"),
    "waist": ("spine", "hips"),
    "hips": ("hips", "leftUpperLeg", "rightUpperLeg"),
    "upperLegs": ("leftUpperLeg", "rightUpperLeg"),
    "lowerLegs": ("leftLowerLeg", "rightLowerLeg"),
    "feet": ("leftFoot", "rightFoot", "leftToes", "rightToes"),
    "upperArms": ("leftUpperArm", "rightUpperArm"),
    "lowerArms": ("leftLowerArm", "rightLowerArm"),
    "shoulders": ("leftShoulder", "rightShoulder", "upperChest", "chest"),
    "neck": ("neck",),
}


@dataclass(slots=True)
class BoneSegment:
    name: str
    node: int
    head: np.ndarray
    tail: np.ndarray

    @property
    def direction(self) -> np.ndarray:
        delta = self.tail - self.head
        length = float(np.linalg.norm(delta))
        return delta / length if length > 1e-9 else np.array([0.0, 1.0, 0.0])


def bones_for_coverage(coverage: list[str]) -> list[str]:
    """Expand a template's coverage regions into candidate bone names."""
    names: list[str] = []
    for region in coverage:
        for bone in COVERAGE_BONES.get(region, ()):
            if bone not in names:
                names.append(bone)
    return names


def build_bone_segments(
    humanoid_bones: dict[str, int],
    measurements: BodyMeasurements,
    candidates: list[str],
) -> list[BoneSegment]:
    """Resolve candidate bone names into positioned segments."""
    positions = measurements.bone_positions
    segments: list[BoneSegment] = []

    for name in candidates:
        node = humanoid_bones.get(name)
        head_position = positions.get(name)
        if node is None or head_position is None:
            continue
        head = np.array(head_position, dtype=np.float64)

        tail: np.ndarray | None = None
        for child in HUMANOID_CHILDREN.get(name, ()):
            child_position = positions.get(child)
            if child_position is not None:
                tail = np.array(child_position, dtype=np.float64)
                break

        if tail is None or float(np.linalg.norm(tail - head)) < 1e-6:
            # Leaf bone: extend a short stub so the segment has a direction.
            stub = max(measurements.height_m * 0.05, 1e-3)
            tail = head + np.array([0.0, stub, 0.0])

        segments.append(BoneSegment(name=name, node=node, head=head, tail=tail))

    return segments


def _sagittal_plane(segments: list[BoneSegment]) -> tuple[float, float, float] | None:
    """Locate the body's midline from the paired bones in ``segments``.

    Returns ``(x, tolerance, left_sign)``. ``left_sign`` is +1 when the
    character's left is at +X, so the convention is measured rather than
    assumed.
    """
    left = [s.head[0] for s in segments if s.name.startswith("left")]
    right = [s.head[0] for s in segments if s.name.startswith("right")]
    if not left or not right:
        return None

    left_mean = float(np.mean(left))
    right_mean = float(np.mean(right))
    separation = abs(left_mean - right_mean)
    if separation < 1e-4:
        return None

    plane = (left_mean + right_mean) * 0.5
    # Vertices within this band of the midline stay free to blend both sides,
    # so a skirt's centre front still follows both legs.
    tolerance = separation * 0.25
    return plane, tolerance, 1.0 if left_mean > right_mean else -1.0


def connected_components(mesh: Mesh) -> np.ndarray:
    """Label each vertex with the index of its connected component."""
    count = mesh.vertex_count
    parent = np.arange(count)

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]  # path halving
            node = parent[node]
        return node

    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    for a, b, c in triangles:
        for x, y in ((a, b), (b, c)):
            root_x, root_y = find(int(x)), find(int(y))
            if root_x != root_y:
                parent[root_y] = root_x

    roots = np.array([find(i) for i in range(count)])
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def _apply_lateral_mask(
    strength: np.ndarray, points: np.ndarray, segments: list[BoneSegment], mesh: Mesh
) -> None:
    """Keep one-sided garment pieces off the opposite side's bones.

    The discriminator is connectivity, not position. A skirt is a single shell
    spanning both legs and *should* blend between them — that is how fabric
    behaves when the legs move apart. A pair of shoes is two separate shells,
    each belonging to one foot; letting the left shoe pick up the right shin
    tears it in half the moment the legs swing in opposite directions.

    So a component is only restricted when it clearly sits on one side.
    """
    plane = _sagittal_plane(segments)
    if plane is None:
        return
    centre, tolerance, left_sign = plane

    offset = (points[:, 0] - centre) * left_sign  # positive == character's left
    labels = connected_components(mesh)

    for label in np.unique(labels):
        member = labels == label
        mean_offset = float(offset[member].mean())
        if abs(mean_offset) <= tolerance:
            continue  # straddles the midline: let it blend

        blocked_prefix = "right" if mean_offset > 0 else "left"
        for index, segment in enumerate(segments):
            if segment.name.startswith(blocked_prefix):
                strength[member, index] = 0.0


def distance_to_segments(points: np.ndarray, segments: list[BoneSegment]) -> np.ndarray:
    """(N, B) distance from each point to each bone segment."""
    heads = np.array([s.head for s in segments])  # (B, 3)
    tails = np.array([s.tail for s in segments])
    axes = tails - heads
    lengths_sq = np.einsum("ij,ij->i", axes, axes)
    lengths_sq[lengths_sq < 1e-12] = 1e-12

    delta = points[:, None, :] - heads[None, :, :]  # (N, B, 3)
    t = np.einsum("nbi,bi->nb", delta, axes) / lengths_sq
    t = np.clip(t, 0.0, 1.0)
    closest = heads[None, :, :] + t[:, :, None] * axes[None, :, :]
    return np.linalg.norm(points[:, None, :] - closest, axis=2)


def bind_mesh(
    mesh: Mesh,
    segments: list[BoneSegment],
    *,
    falloff: float = 2.5,
    max_influences: int = MAX_INFLUENCES,
    max_distance_ratio: float = 2.2,
) -> Mesh:
    """Assign ``joints``/``weights`` on ``mesh`` in place and return it.

    Joint values index into ``segments``; :func:`wardrobe.vrm.merge.attach_garment`
    turns those into glTF skin joint indices.

    ``max_distance_ratio`` discards influences far outside the nearest bone.
    Without it, inverse-distance weighting bleeds across the body's midline —
    a left shoe picks up the right shin, and the garment tears the moment the
    legs move in opposite directions.
    """
    if not segments:
        raise ValueError("cannot bind a garment without any candidate bones")

    points = mesh.positions.astype(np.float64)
    distances = distance_to_segments(points, segments)

    # Inverse-distance weighting, then keep the strongest influences.
    epsilon = max(float(np.median(distances)) * 0.05, 1e-4)
    strength = 1.0 / np.power(distances + epsilon, falloff)
    _apply_lateral_mask(strength, points, segments, mesh)

    influences = min(max_influences, len(segments))
    order = np.argsort(-strength, axis=1)[:, :influences]
    rows = np.arange(points.shape[0])[:, None]
    top = strength[rows, order]

    # Drop influences that are disproportionately far from the closest bone.
    top_distances = distances[rows, order]
    nearest = distances.min(axis=1, keepdims=True)
    within_reach = top_distances <= nearest * max_distance_ratio + epsilon
    within_reach[:, 0] = True  # the nearest bone is always kept
    top = np.where(within_reach, top, 0.0)

    totals = top.sum(axis=1, keepdims=True)
    totals[totals < 1e-12] = 1.0
    normalised = top / totals

    joints = np.zeros((points.shape[0], MAX_INFLUENCES), dtype=np.uint16)
    weights = np.zeros((points.shape[0], MAX_INFLUENCES), dtype=np.float32)
    joints[:, :influences] = order.astype(np.uint16)
    weights[:, :influences] = normalised.astype(np.float32)

    # Guarantee an exact sum of 1.0 per vertex after float32 rounding.
    residual = 1.0 - weights.sum(axis=1)
    weights[:, 0] += residual.astype(np.float32)

    mesh.joints = joints
    mesh.weights = weights
    mesh.metadata["boundBones"] = [s.name for s in segments]
    return mesh


def weight_report(mesh: Mesh, segments: list[BoneSegment]) -> dict:
    """Summary used by the fit report and by CI acceptance checks."""
    if mesh.weights is None or mesh.joints is None:
        return {"valid": False, "reason": "mesh has no skin weights"}

    sums = mesh.weights.sum(axis=1)
    used = sorted(
        {
            segments[j].name
            for row, weights in zip(mesh.joints, mesh.weights, strict=True)
            for j, weight in zip(row, weights, strict=True)
            if weight > 0
        }
    )

    return {
        "valid": bool(np.allclose(sums, 1.0, atol=1e-3)) and bool((mesh.weights >= 0).all()),
        "vertexCount": mesh.vertex_count,
        "minWeightSum": float(sums.min()),
        "maxWeightSum": float(sums.max()),
        "maxInfluences": int((mesh.weights > 0).sum(axis=1).max()),
        "bonesUsed": used,
    }


__all__ = [
    "BoneSegment",
    "COVERAGE_BONES",
    "HUMANOID_CHILDREN",
    "MAX_INFLUENCES",
    "bones_for_coverage",
    "build_bone_segments",
    "bind_mesh",
    "weight_report",
]
