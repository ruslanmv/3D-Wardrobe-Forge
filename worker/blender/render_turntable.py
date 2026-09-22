"""Render the preview image for a generated look."""

from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector


def _frame_target(objects) -> tuple[Vector, float]:
    low = Vector((float("inf"),) * 3)
    high = Vector((float("-inf"),) * 3)
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], point[axis])
                high[axis] = max(high[axis], point[axis])

    if low.x == float("inf"):
        return Vector((0.0, 0.0, 0.8)), 1.6
    return (low + high) * 0.5, max((high - low).length, 0.5)


def setup_scene(objects, *, width: int, height: int) -> None:
    scene = bpy.context.scene
    centre, size = _frame_target(objects)

    camera_data = bpy.data.cameras.new("WardrobePreviewCamera")
    camera_data.lens = 55
    camera = bpy.data.objects.new("WardrobePreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)

    distance = size * 1.5
    camera.location = centre + Vector((0.0, -distance, size * 0.08))
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera

    key = bpy.data.lights.new("WardrobeKey", type="AREA")
    key.energy = 400.0
    key.size = size
    key_object = bpy.data.objects.new("WardrobeKey", key)
    key_object.location = centre + Vector((-size, -size, size))
    key_object.rotation_euler = (math.radians(55.0), 0.0, math.radians(-35.0))
    bpy.context.collection.objects.link(key_object)

    fill = bpy.data.lights.new("WardrobeFill", type="AREA")
    fill.energy = 120.0
    fill.size = size
    fill_object = bpy.data.objects.new("WardrobeFill", fill)
    fill_object.location = centre + Vector((size, -size * 0.6, size * 0.5))
    fill_object.rotation_euler = (math.radians(70.0), 0.0, math.radians(40.0))
    bpy.context.collection.objects.link(fill_object)

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False

    world = scene.world or bpy.data.worlds.new("WardrobeWorld")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.11, 0.12, 0.14, 1.0)


def render(filepath: str, objects, *, width: int = 512, height: int = 768, samples: int = 32) -> dict:
    """Render a single front view. Returns what was written."""
    setup_scene(objects, width=width, height=height)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if _has_engine("BLENDER_EEVEE_NEXT") else "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = samples

    extension = os.path.splitext(filepath)[1].lower()
    scene.render.image_settings.file_format = "WEBP" if extension == ".webp" else "PNG"
    if scene.render.image_settings.file_format == "WEBP":
        scene.render.image_settings.quality = 88

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)

    if not os.path.exists(filepath):
        return {"rendered": False}
    return {"rendered": True, "path": filepath, "sizeBytes": os.path.getsize(filepath)}


def _has_engine(identifier: str) -> bool:
    try:
        return identifier in {
            item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
        }
    except (KeyError, AttributeError):
        return False


__all__ = ["render", "setup_scene"]
