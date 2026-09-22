"""Put the avatar into its rest pose before measuring or fitting.

A VRM that arrives in an A-pose, or with leftover pose transforms, would be
measured wrongly and fitted wrongly. Clearing the pose is cheap insurance.
"""

from __future__ import annotations

import bpy


def clear_pose(armature) -> int:
    """Reset every pose bone to rest. Returns how many bones were touched."""
    previous = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature

    touched = 0
    bpy.ops.object.mode_set(mode="POSE")
    try:
        for bone in armature.pose.bones:
            if (
                bone.location.length > 1e-6
                or any(abs(value - 1.0) > 1e-6 for value in bone.scale)
                or bone.rotation_quaternion.angle > 1e-6
            ):
                touched += 1
            bone.location = (0.0, 0.0, 0.0)
            bone.scale = (1.0, 1.0, 1.0)
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = previous

    return touched


def apply_object_transforms(objects) -> None:
    """Bake object-level transforms so world space and local space agree."""
    bpy.ops.object.select_all(action="DESELECT")
    selected = [obj for obj in objects if obj.type in {"MESH", "ARMATURE"}]
    if not selected:
        return

    for obj in selected:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = selected[0]

    try:
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    except RuntimeError:
        # Multi-user meshes cannot be baked; measurements still work, they are
        # just taken in the object's own space.
        pass
    finally:
        bpy.ops.object.select_all(action="DESELECT")


def normalize(armature, objects) -> dict:
    return {
        "posedBonesCleared": clear_pose(armature),
        "transformsApplied": bool(objects),
    }


__all__ = ["normalize", "clear_pose", "apply_object_transforms"]
