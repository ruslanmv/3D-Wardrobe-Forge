"""Measure the avatar inside Blender.

Mirrors :mod:`wardrobe.vrm.measure` so the two engines agree on what a body is,
but takes the values from the evaluated Blender scene, which accounts for
modifiers and shape keys the glTF-level reader cannot see.
"""

from __future__ import annotations

import bpy
from mathutils import Vector

from worker.blender.analyze_humanoid import world_head


def _bounds(meshes) -> tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    low = Vector((float("inf"),) * 3)
    high = Vector((float("-inf"),) * 3)

    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        for corner in evaluated.bound_box:
            point = evaluated.matrix_world @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], point[axis])
                high[axis] = max(high[axis], point[axis])
    return low, high


def measure(armature, meshes, bones: dict[str, str]) -> dict:
    """Return the same measurement dictionary the native engine produces."""
    low, high = _bounds(meshes)
    height = float(high.z - low.z)
    depth = float(high.y - low.y)

    positions: dict[str, Vector] = {}
    for humanoid, bone_name in bones.items():
        head = world_head(armature, bone_name)
        if head is not None:
            positions[humanoid] = head

    def distance(left: str, right: str) -> float | None:
        a, b = positions.get(left), positions.get(right)
        return float((a - b).length) if a is not None and b is not None else None

    def chain(*names: str) -> float | None:
        points = [positions.get(name) for name in names]
        if any(point is None for point in points):
            return None
        return float(sum((b - a).length for a, b in zip(points, points[1:])))

    shoulder = distance("leftUpperArm", "rightUpperArm") or height * 0.235
    hip = (distance("leftUpperLeg", "rightUpperLeg") or height * 0.10) * 1.85
    chest = shoulder * 0.88
    waist = (chest + hip) * 0.5 * 0.86

    arm = chain("leftUpperArm", "leftLowerArm", "leftHand") or height * 0.44
    leg = chain("leftUpperLeg", "leftLowerLeg", "leftFoot") or height * 0.48

    upper_leg = positions.get("leftUpperLeg")
    foot = positions.get("leftFoot")
    inseam = float(abs(upper_leg.z - foot.z)) if upper_leg and foot else leg * 0.95

    return {
        "heightM": round(height, 4),
        "shoulderWidthM": round(shoulder, 4),
        "chestWidthM": round(chest, 4),
        "waistWidthM": round(waist, 4),
        "hipWidthM": round(hip, 4),
        "armLengthM": round(arm, 4),
        "legLengthM": round(leg, 4),
        "inseamM": round(inseam, 4),
        "depthM": round(depth, 4),
        "bonePositions": {name: [round(v, 4) for v in position] for name, position in positions.items()},
        "bounds": [[round(v, 4) for v in low], [round(v, 4) for v in high]],
        "source": "blender",
    }


__all__ = ["measure"]
