"""Hide the body polygons the garment covers.

This is the capability the native engine does not have. Without it, a tight
garment shows skin poking through wherever the body is denser than the shell.

The body is never destroyed: covered faces are collected into a vertex group
and hidden with a Mask modifier, so the original geometry is still present and
the effect can be reversed.
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

MASK_GROUP = "WardrobeForgeBodyMask"


def _garment_tree(garment) -> BVHTree:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = garment.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(garment.matrix_world)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    evaluated.to_mesh_clear()
    return tree


def covered_vertices(body, garment, *, margin_m: float = 0.02) -> list[int]:
    """Body vertex indices that lie underneath the garment shell."""
    tree = _garment_tree(garment)
    matrix = body.matrix_world

    covered: list[int] = []
    for vertex in body.data.vertices:
        point = matrix @ vertex.co
        location, normal, _, _ = tree.find_nearest(point)
        if location is None:
            continue
        distance = (point - location).length
        if distance > margin_m:
            continue
        # Negative dot product means the point is on the inner side of the shell.
        if (point - location).dot(normal) < 0.0:
            covered.append(vertex.index)
    return covered


def apply_mask(body, garment, *, margin_m: float = 0.02, keep_border: bool = True) -> dict:
    """Create the mask vertex group and the Mask modifier that hides it."""
    covered = covered_vertices(body, garment, margin_m=margin_m)
    if not covered:
        return {"masked": False, "coveredVertices": 0}

    group = body.vertex_groups.get(MASK_GROUP) or body.vertex_groups.new(name=MASK_GROUP)
    # The group marks what to KEEP, so start at 1.0 and zero the covered part.
    group.add([vertex.index for vertex in body.data.vertices], 1.0, "REPLACE")
    group.add(covered, 0.0, "REPLACE")

    if keep_border:
        _feather_border(body, group, covered)

    modifier = body.modifiers.get("WardrobeBodyMask")
    if modifier is None:
        modifier = body.modifiers.new(name="WardrobeBodyMask", type="MASK")
    modifier.vertex_group = MASK_GROUP
    modifier.threshold = 0.5
    modifier.show_in_editmode = True

    return {
        "masked": True,
        "coveredVertices": len(covered),
        "bodyVertices": len(body.data.vertices),
        "coveredRatio": round(len(covered) / max(len(body.data.vertices), 1), 5),
        "vertexGroup": MASK_GROUP,
    }


def _feather_border(body, group, covered: list[int]) -> None:
    """Keep one ring of vertices around the hole so no gap appears at the hem."""
    covered_set = set(covered)
    border: set[int] = set()

    for edge in body.data.edges:
        a, b = edge.vertices
        if (a in covered_set) != (b in covered_set):
            border.add(a if a in covered_set else b)

    if border:
        group.add(sorted(border), 1.0, "REPLACE")


def remove_mask(body) -> None:
    modifier = body.modifiers.get("WardrobeBodyMask")
    if modifier is not None:
        body.modifiers.remove(modifier)
    group = body.vertex_groups.get(MASK_GROUP)
    if group is not None:
        body.vertex_groups.remove(group)


__all__ = ["apply_mask", "covered_vertices", "remove_mask", "MASK_GROUP"]
