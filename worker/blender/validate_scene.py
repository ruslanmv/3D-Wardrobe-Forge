"""In-Blender sanity checks and pose tests, run before export.

Catching a broken bind here saves a full export/re-import cycle, and the pose
tests are the ones that matter for an avatar that will be animated.
"""

from __future__ import annotations

import bpy
from mathutils import Euler, Vector

#: Degrees of rotation per bone, per named test pose.
POSE_TESTS: dict[str, dict[str, tuple[float, float, float]]] = {
    "arms-down": {"leftUpperArm": (0, 0, -65), "rightUpperArm": (0, 0, 65)},
    "walk": {"leftUpperLeg": (28, 0, 0), "rightUpperLeg": (-28, 0, 0)},
    "sit": {
        "leftUpperLeg": (85, 0, 0), "rightUpperLeg": (85, 0, 0),
        "leftLowerLeg": (-85, 0, 0), "rightLowerLeg": (-85, 0, 0),
    },
    "legs-apart": {"leftUpperLeg": (0, 0, -22), "rightUpperLeg": (0, 0, 22)},
}


def check_scene(armature, body, garment) -> list[str]:
    """Structural problems that would produce a broken VRM."""
    issues: list[str] = []

    if armature is None:
        issues.append("no armature in the scene")
    if body is None or len(body.data.vertices) == 0:
        issues.append("the body mesh is empty")

    if garment is not None:
        if len(garment.data.vertices) == 0:
            issues.append("the garment mesh is empty")
        if not any(modifier.type == "ARMATURE" for modifier in garment.modifiers):
            issues.append("the garment has no armature modifier; it will not deform")
        if not garment.vertex_groups:
            issues.append("the garment has no vertex groups; it has no skin weights")
        if not garment.data.materials:
            issues.append("the garment has no material")

    for obj in (body, garment):
        if obj is None:
            continue
        for vertex in obj.data.vertices:
            if not all(_finite(value) for value in vertex.co):
                issues.append(f"{obj.name} contains non-finite vertex positions")
                break

    return issues


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _evaluated_bounds(obj) -> tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if not mesh.vertices:
            return Vector((0, 0, 0)), Vector((0, 0, 0))
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        low = Vector((min(p[i] for p in points) for i in range(3)))
        high = Vector((max(p[i] for p in points) for i in range(3)))
        return low, high
    finally:
        evaluated.to_mesh_clear()


def run_pose_tests(armature, garment, bones: dict[str, str]) -> dict:
    """Pose the rig and confirm the garment follows without exploding."""
    if garment is None or armature is None:
        return {"checked": False}

    rest_low, rest_high = _evaluated_bounds(garment)
    rest_size = (rest_high - rest_low).length or 1.0

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    results: dict[str, dict] = {}
    passed = True

    try:
        for pose_name, rotations in POSE_TESTS.items():
            applied = 0
            for humanoid, degrees in rotations.items():
                bone_name = bones.get(humanoid)
                pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
                if pose_bone is None:
                    continue
                pose_bone.rotation_mode = "XYZ"
                pose_bone.rotation_euler = Euler([d * 3.14159265 / 180.0 for d in degrees], "XYZ")
                applied += 1

            if applied == 0:
                results[pose_name] = {"applies": False}
                continue

            bpy.context.view_layer.update()
            low, high = _evaluated_bounds(garment)
            size = (high - low).length
            growth = size / rest_size

            finite = all(_finite(value) for value in list(low) + list(high))
            # A garment that more than doubles its bounding box under a normal
            # pose has a weighting fault, not a design.
            ok = finite and growth < 2.0
            passed = passed and ok
            results[pose_name] = {
                "applies": True,
                "finite": finite,
                "boundsGrowth": round(growth, 3),
                "passed": ok,
            }

            for humanoid in rotations:
                bone_name = bones.get(humanoid)
                pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
                if pose_bone is not None:
                    pose_bone.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
            bpy.context.view_layer.update()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    results["checked"] = True
    results["passed"] = passed
    return results


__all__ = ["check_scene", "run_pose_tests", "POSE_TESTS"]
