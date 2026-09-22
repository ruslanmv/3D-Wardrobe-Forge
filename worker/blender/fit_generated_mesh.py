"""Clean up and fit a mesh that came from an AI 3D provider.

Generated meshes are untrustworthy geometry: unwelded vertices, loose parts,
inconsistent normals, unknown scale and unknown orientation. Nothing here is
optional — skipping it produces a garment that cannot be weighted.
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector


def clean(obj, *, merge_distance: float = 0.0008) -> dict:
    """Weld, drop loose geometry, fix normals and triangulate."""
    mesh = obj.data
    before = len(mesh.vertices)

    bm = bmesh.new()
    bm.from_mesh(mesh)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    return {"verticesBefore": before, "verticesAfter": len(mesh.vertices)}


def keep_largest_shell(obj) -> int:
    """Discard stray floating parts, keeping the biggest connected component."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    components: list[set] = []
    unvisited = set(bm.verts)
    while unvisited:
        seed = unvisited.pop()
        component = {seed}
        stack = [seed]
        while stack:
            vertex = stack.pop()
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other in unvisited:
                    unvisited.discard(other)
                    component.add(other)
                    stack.append(other)
        components.append(component)

    removed = 0
    if len(components) > 1:
        largest = max(components, key=len)
        doomed = [vertex for component in components if component is not largest for vertex in component]
        removed = len(doomed)
        bmesh.ops.delete(bm, geom=doomed, context="VERTS")

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return removed


def decimate(obj, *, target_triangles: int) -> dict:
    """Reduce a dense generated mesh to a real-time budget."""
    triangles = len(obj.data.polygons)
    if triangles <= target_triangles:
        return {"decimated": False, "triangles": triangles}

    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new(name="WardrobeDecimate", type="DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = max(target_triangles / triangles, 0.05)
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    return {"decimated": True, "triangles": len(obj.data.polygons)}


def align_to_body(obj, measurements: dict) -> dict:
    """Scale and place an arbitrarily sized generated mesh onto the body.

    Providers return models in their own units and orientation, so the mesh is
    normalised to the body's torso height and centred on its vertical axis.
    """
    bounds = measurements.get("bounds")
    height = float(measurements.get("heightM", 0.0))
    if not bounds or height <= 0:
        return {"aligned": False}

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    local = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = Vector((min(p[i] for p in local) for i in range(3)))
    high = Vector((max(p[i] for p in local) for i in range(3)))
    size = high - low
    if size.z <= 1e-6:
        return {"aligned": False}

    # Garments occupy roughly 45% of a figure's height; close enough for the
    # shrinkwrap pass to finish the job.
    scale = (height * 0.45) / size.z
    obj.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    body_low, body_high = Vector(bounds[0]), Vector(bounds[1])
    centre = (low + high) * 0.5 * scale
    obj.location.x += (body_low.x + body_high.x) * 0.5 - centre.x
    obj.location.y += (body_low.y + body_high.y) * 0.5 - centre.y
    obj.location.z += body_low.z + (body_high.z - body_low.z) * 0.55 - centre.z

    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    return {"aligned": True, "scale": round(scale, 5)}


def prepare(obj, measurements: dict, *, target_triangles: int = 8000) -> dict:
    report = {"clean": clean(obj)}
    report["looseVerticesRemoved"] = keep_largest_shell(obj)
    report["decimate"] = decimate(obj, target_triangles=target_triangles)
    report["align"] = align_to_body(obj, measurements)
    return report


__all__ = ["prepare", "clean", "keep_largest_shell", "decimate", "align_to_body"]
