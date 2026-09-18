"""Resolve humanoid bones inside Blender.

Three sources are tried in order: the bone names the orchestrator read out of
the glTF (authoritative), the VRM add-on's own humanoid mapping, and finally a
name heuristic for rigs where neither is available.
"""

from __future__ import annotations

import bpy

#: Lower-cased substrings that identify each humanoid bone in common rigs.
NAME_HINTS: dict[str, tuple[str, ...]] = {
    "hips": ("hips", "pelvis"),
    "spine": ("spine",),
    "chest": ("chest",),
    "upperChest": ("upperchest", "chest_upper"),
    "neck": ("neck",),
    "head": ("head",),
    "leftShoulder": ("shoulder_l", "l_shoulder", "leftshoulder", "clavicle_l"),
    "rightShoulder": ("shoulder_r", "r_shoulder", "rightshoulder", "clavicle_r"),
    "leftUpperArm": ("upperarm_l", "l_upperarm", "leftupperarm", "arm_l"),
    "rightUpperArm": ("upperarm_r", "r_upperarm", "rightupperarm", "arm_r"),
    "leftLowerArm": ("lowerarm_l", "l_lowerarm", "leftlowerarm", "forearm_l"),
    "rightLowerArm": ("lowerarm_r", "r_lowerarm", "rightlowerarm", "forearm_r"),
    "leftHand": ("hand_l", "l_hand", "lefthand"),
    "rightHand": ("hand_r", "r_hand", "righthand"),
    "leftUpperLeg": ("upperleg_l", "l_upperleg", "leftupperleg", "thigh_l"),
    "rightUpperLeg": ("upperleg_r", "r_upperleg", "rightupperleg", "thigh_r"),
    "leftLowerLeg": ("lowerleg_l", "l_lowerleg", "leftlowerleg", "shin_l", "calf_l"),
    "rightLowerLeg": ("lowerleg_r", "r_lowerleg", "rightlowerleg", "shin_r", "calf_r"),
    "leftFoot": ("foot_l", "l_foot", "leftfoot"),
    "rightFoot": ("foot_r", "r_foot", "rightfoot"),
    "leftToes": ("toe_l", "l_toe", "lefttoe"),
    "rightToes": ("toe_r", "r_toe", "righttoe"),
}

REQUIRED = (
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)


def _from_vrm_addon(armature) -> dict[str, str]:
    """Read the add-on's humanoid mapping, across its VRM 0.x / 1.0 layouts."""
    extension = getattr(armature.data, "vrm_addon_extension", None)
    if extension is None:
        return {}

    mapping: dict[str, str] = {}
    human_bones = getattr(getattr(extension, "vrm1", None), "humanoid", None)
    if human_bones is not None and hasattr(human_bones, "human_bones"):
        for name in dir(human_bones.human_bones):
            if name.startswith("_"):
                continue
            entry = getattr(human_bones.human_bones, name, None)
            bone_name = getattr(entry, "node", None)
            bone_name = getattr(bone_name, "bone_name", None)
            if bone_name:
                mapping[_camel(name)] = bone_name

    if mapping:
        return mapping

    legacy = getattr(getattr(extension, "vrm0", None), "humanoid", None)
    for bone in getattr(legacy, "human_bones", []) or []:
        if getattr(bone, "bone", None) and getattr(bone, "node", None):
            bone_name = getattr(bone.node, "bone_name", None)
            if bone_name:
                mapping[str(bone.bone)] = bone_name
    return mapping


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(part.title() for part in rest)


def _from_names(armature) -> dict[str, str]:
    mapping: dict[str, str] = {}
    bones = list(armature.data.bones)
    for humanoid, hints in NAME_HINTS.items():
        for bone in bones:
            lowered = bone.name.lower().replace(" ", "").replace(".", "_")
            if any(hint in lowered for hint in hints):
                mapping.setdefault(humanoid, bone.name)
                break
    return mapping


def analyze_humanoid(armature, declared: dict[str, str] | None = None) -> dict:
    """Return ``{"bones": {humanoid: blender_bone_name}, "missing": [...]}``."""
    existing = {bone.name for bone in armature.data.bones}

    mapping: dict[str, str] = {}
    for humanoid, bone_name in (declared or {}).items():
        if bone_name in existing:
            mapping[humanoid] = bone_name

    for source in (_from_vrm_addon(armature), _from_names(armature)):
        for humanoid, bone_name in source.items():
            if humanoid not in mapping and bone_name in existing:
                mapping[humanoid] = bone_name

    missing = [bone for bone in REQUIRED if bone not in mapping]
    return {"bones": mapping, "missing": missing, "boneCount": len(existing)}


def world_head(armature, bone_name: str):
    """World-space head position of a bone."""
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        return None
    return armature.matrix_world @ bone.head_local


__all__ = ["analyze_humanoid", "world_head", "NAME_HINTS", "REQUIRED"]
