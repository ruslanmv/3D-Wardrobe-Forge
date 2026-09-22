"""Detect and repair body/garment intersections."""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def build_body_tree(body) -> BVHTree:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(body.matrix_world)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    evaluated.to_mesh_clear()
    return tree


def _is_inside(tree: BVHTree, point: Vector) -> bool:
    """Inside test by surface normal: the nearest face points away from us."""
    location, normal, _, _ = tree.find_nearest(point)
    if location is None:
        return False
    return (point - location).dot(normal) < 0.0


def detect(garment, body, *, clearance_m: float) -> dict:
    """Count garment vertices that sit inside, or too close to, the body."""
    tree = build_body_tree(body)
    matrix = garment.matrix_world

    inside = 0
    too_close = 0
    minimum = float("inf")

    for vertex in garment.data.vertices:
        point = matrix @ vertex.co
        location, _, _, _ = tree.find_nearest(point)
        if location is None:
            continue
        distance = (point - location).length
        minimum = min(minimum, distance)
        if _is_inside(tree, point):
            inside += 1
        elif distance < clearance_m * 0.5:
            too_close += 1

    total = max(len(garment.data.vertices), 1)
    return {
        "insideVertices": inside,
        "tooCloseVertices": too_close,
        "violationRatio": round((inside + too_close) / total, 5),
        "minDistanceMm": round(minimum * 1000.0, 2) if minimum != float("inf") else None,
    }


def repair(garment, body, *, clearance_m: float, iterations: int = 3) -> dict:
    """Push intersecting vertices out along the body's surface normal."""
    tree = build_body_tree(body)
    matrix = garment.matrix_world
    inverse = matrix.inverted()

    moved = 0
    for _ in range(iterations):
        moved_this_pass = 0
        for vertex in garment.data.vertices:
            point = matrix @ vertex.co
            location, normal, _, _ = tree.find_nearest(point)
            if location is None:
                continue
            offset = (point - location).dot(normal)
            if offset >= clearance_m:
                continue
            vertex.co = inverse @ (location + normal * clearance_m)
            moved_this_pass += 1

        moved += moved_this_pass
        if moved_this_pass == 0:
            break

    garment.data.update()
    return {"verticesMoved": moved, "clearanceMm": round(clearance_m * 1000.0, 2)}


def verdict(report: dict) -> str:
    """Map an intersection report to a fit-report clipping state."""
    ratio = report.get("violationRatio", 0.0)
    if ratio == 0.0:
        return "passed"
    if ratio < 0.02:
        return "warnings"
    return "failed"


__all__ = ["detect", "repair", "verdict", "build_body_tree"]
