"""Write a standalone mesh out as a GLB.

Used to hand the procedurally built garment shell to Blender, and useful on its
own for inspecting a generated garment in any glTF viewer.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument
from wardrobe.vrm.merge import GarmentMaterial


def mesh_to_glb(mesh: Mesh, *, name: str = "Garment", material: GarmentMaterial | None = None) -> bytes:
    """Serialise ``mesh`` as a single-node, single-primitive GLB."""
    issues = [issue for issue in mesh.validate() if "skin weights" not in issue]
    if issues:
        raise ValueError("; ".join(issues))

    document = GltfDocument(
        {
            "asset": {"version": "2.0", "generator": "3D-Wardrobe-Forge"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [],
            "buffers": [{"byteLength": 0}],
        },
        b"",
    )

    normals = mesh.normals if mesh.normals is not None else mesh.compute_normals().normals
    uvs = mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), dtype=np.float32)

    attributes = {
        "POSITION": document.add_accessor(
            mesh.positions.astype(np.float32), target=ARRAY_BUFFER, include_bounds=True
        ),
        "NORMAL": document.add_accessor(normals.astype(np.float32), target=ARRAY_BUFFER),
        "TEXCOORD_0": document.add_accessor(uvs.astype(np.float32), target=ARRAY_BUFFER),
    }
    indices = document.add_accessor(
        mesh.indices.astype(np.uint32).reshape(-1, 1), target=ELEMENT_ARRAY_BUFFER
    )

    material_index = (material or GarmentMaterial(name=name)).add_to(document)
    mesh_index = document.add_mesh(
        [{"attributes": attributes, "indices": indices, "material": material_index, "mode": 4}], name=name
    )

    document.gltf["nodes"] = [{"name": name, "mesh": mesh_index}]
    document.gltf["scenes"] = [{"nodes": [0]}]
    return document.to_bytes()


__all__ = ["mesh_to_glb"]
