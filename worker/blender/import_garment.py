"""Import garment geometry into the scene.

Two sources: the measured shell the orchestrator built (a plain GLB), or a mesh
downloaded from an AI provider, which needs cleanup first.
"""

from __future__ import annotations

import bpy


def import_glb(filepath: str, *, name: str = "Garment"):
    """Import a GLB and return its merged mesh object."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    imported = [obj for obj in bpy.data.objects if obj not in before]

    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh found in garment file: {filepath}")

    garment = meshes[0]
    if len(meshes) > 1:
        garment = join(meshes)

    # Drop the empties the glTF importer adds around the scene root.
    for obj in imported:
        if obj.type == "EMPTY" and not obj.children:
            bpy.data.objects.remove(obj, do_unlink=True)

    garment.name = name
    garment.data.name = f"{name}Mesh"

    # Parenting comes later, from the armature; a leftover parent transform
    # would double-apply once the garment is skinned.
    garment.parent = None
    garment.matrix_parent_inverse.identity()
    return garment


def join(objects):
    """Join mesh objects into the first one and return it."""
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def strip_rig(obj) -> None:
    """Remove any armature the provider's mesh arrived with."""
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)
    obj.vertex_groups.clear()


__all__ = ["import_glb", "join", "strip_rig"]
