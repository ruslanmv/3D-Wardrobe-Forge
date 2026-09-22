"""Import a VRM into the current Blender scene.

Requires the VRM Add-on for Blender (``bpy.ops.import_scene.vrm``). If the
add-on is missing we fall back to the glTF importer, which loads the geometry
and armature but drops the VRM extension data — enough to fail loudly with a
useful message rather than silently exporting a broken avatar.
"""

from __future__ import annotations

import bpy


class VrmAddonMissing(RuntimeError):
    """The VRM add-on is not enabled in this Blender install."""


def ensure_vrm_addon() -> bool:
    """Enable the VRM add-on if it is installed. Returns whether it is usable."""
    if hasattr(bpy.ops.import_scene, "vrm"):
        return True
    for module in ("io_scene_vrm", "VRM_Addon_for_Blender"):
        try:
            bpy.ops.preferences.addon_enable(module=module)
        except Exception:  # noqa: BLE001 - any failure just means "not available"
            continue
        if hasattr(bpy.ops.import_scene, "vrm"):
            return True
    return False


def clear_scene() -> None:
    """Start from an empty scene; ``--factory-startup`` still ships a cube."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.armatures, bpy.data.materials, bpy.data.images):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def import_vrm(filepath: str) -> dict:
    """Import ``filepath`` and return the armature plus its mesh objects."""
    before = set(bpy.data.objects)

    if ensure_vrm_addon():
        bpy.ops.import_scene.vrm(filepath=filepath)
        used_addon = True
    else:
        bpy.ops.import_scene.gltf(filepath=filepath)
        used_addon = False

    imported = [obj for obj in bpy.data.objects if obj not in before]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    meshes = [obj for obj in imported if obj.type == "MESH"]

    if not armatures:
        raise RuntimeError("the imported VRM contains no armature; it is not a riggable humanoid")
    if not meshes:
        raise RuntimeError("the imported VRM contains no mesh objects")

    return {
        "armature": armatures[0],
        "meshes": meshes,
        "objects": imported,
        "usedVrmAddon": used_addon,
    }


def largest_mesh(meshes: list) -> object:
    """The body mesh: the one with the most vertices."""
    return max(meshes, key=lambda obj: len(obj.data.vertices))


__all__ = ["import_vrm", "ensure_vrm_addon", "clear_scene", "largest_mesh", "VrmAddonMissing"]
