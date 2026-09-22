"""Export the modified scene back out as a VRM."""

from __future__ import annotations

import os

import bpy

from worker.blender.import_vrm import ensure_vrm_addon


def export_vrm(filepath: str, *, armature=None, output_version: str = "source") -> dict:
    """Write the scene to ``filepath`` using the VRM add-on's exporter."""
    if not ensure_vrm_addon():
        raise RuntimeError(
            "the VRM Add-on for Blender is required to export a VRM; "
            "install it in the worker image"
        )

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    if armature is not None:
        bpy.ops.object.select_all(action="DESELECT")
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

    kwargs: dict = {"filepath": filepath}
    # The exporter gained export_invisibles/armature_object_name over time;
    # pass only what this build accepts.
    signature = getattr(bpy.ops.export_scene.vrm, "get_rna_type", None)
    if signature is not None:
        properties = {prop.identifier for prop in signature().properties}
        if armature is not None and "armature_object_name" in properties:
            kwargs["armature_object_name"] = armature.name
        if "export_invisibles" in properties:
            kwargs["export_invisibles"] = False

    bpy.ops.export_scene.vrm(**kwargs)

    if not os.path.exists(filepath):
        raise RuntimeError(f"the VRM exporter reported success but wrote no file: {filepath}")

    return {
        "path": filepath,
        "sizeBytes": os.path.getsize(filepath),
        "requestedVersion": output_version,
    }


def export_glb(filepath: str) -> dict:
    """Fallback export used for debugging when the VRM exporter is unavailable."""
    bpy.ops.export_scene.gltf(filepath=filepath, export_format="GLB", export_skins=True)
    return {"path": filepath, "sizeBytes": os.path.getsize(filepath)}


__all__ = ["export_vrm", "export_glb"]
