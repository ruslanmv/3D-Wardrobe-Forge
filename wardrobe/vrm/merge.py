"""Attach a skinned garment mesh to an existing VRM document.

This is real glTF surgery: new buffer views, accessors, a material, a mesh, a
skin whose joints are the avatar's own humanoid nodes, and the VRM-specific
bookkeeping (first-person annotations, VRM 0.x material properties).

Because the garment is authored in the avatar's rest-pose world space and the
garment node stays at the scene root with an identity transform, the inverse
bind matrices are simply the inverses of each joint's world matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument
from wardrobe.vrm.inspect import VRM0_EXTENSION, VRM1_EXTENSION, VrmInfo, VrmSpec
from wardrobe.vrm.skinning import BoneSegment


@dataclass(slots=True)
class GarmentMaterial:
    name: str = "Garment"
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.7
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
    double_sided: bool = True

    def to_gltf(self) -> dict:
        material: dict = {
            "name": self.name,
            "doubleSided": self.double_sided,
            "pbrMetallicRoughness": {
                "baseColorFactor": [float(c) for c in self.base_color],
                "metallicFactor": float(self.metallic),
                "roughnessFactor": float(self.roughness),
            },
        }
        if any(self.emissive):
            material["emissiveFactor"] = [float(c) for c in self.emissive]
        return material


@dataclass(slots=True)
class AttachResult:
    node_index: int
    mesh_index: int
    skin_index: int
    material_index: int
    joint_nodes: list[int]
    vertex_count: int
    triangle_count: int


class AttachError(ValueError):
    pass


def attach_garment(
    document: GltfDocument,
    info: VrmInfo,
    mesh: Mesh,
    segments: list[BoneSegment],
    *,
    material: GarmentMaterial | None = None,
    name: str = "Garment",
) -> AttachResult:
    """Insert ``mesh`` into ``document`` as a skinned VRM garment."""
    issues = mesh.validate()
    if issues:
        raise AttachError("; ".join(issues))
    if mesh.joints is None or mesh.weights is None:
        raise AttachError("garment mesh must be skin-bound before it can be attached")
    if not segments:
        raise AttachError("garment mesh has no bone segments")

    # ---- map segment indices onto a deduplicated joint list --------------
    joint_nodes: list[int] = []
    segment_to_joint: list[int] = []
    for segment in segments:
        if segment.node in joint_nodes:
            segment_to_joint.append(joint_nodes.index(segment.node))
        else:
            segment_to_joint.append(len(joint_nodes))
            joint_nodes.append(segment.node)

    lookup = np.array(segment_to_joint, dtype=np.uint16)
    joints = lookup[np.clip(mesh.joints, 0, len(segment_to_joint) - 1)].astype(np.uint16)

    # ---- inverse bind matrices ------------------------------------------
    world = document.world_matrices()
    ibm = np.zeros((len(joint_nodes), 16), dtype=np.float32)
    for row, node in enumerate(joint_nodes):
        try:
            inverse = np.linalg.inv(world[node])
        except np.linalg.LinAlgError as exc:  # pragma: no cover - degenerate rig
            raise AttachError(f"joint node {node} has a non-invertible world matrix") from exc
        ibm[row] = inverse.T.reshape(-1).astype(np.float32)  # glTF is column-major

    # ---- accessors -------------------------------------------------------
    normals = mesh.normals if mesh.normals is not None else mesh.compute_normals().normals
    uvs = mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), dtype=np.float32)

    attributes = {
        "POSITION": document.add_accessor(
            mesh.positions.astype(np.float32), target=ARRAY_BUFFER, include_bounds=True
        ),
        "NORMAL": document.add_accessor(normals.astype(np.float32), target=ARRAY_BUFFER),
        "TEXCOORD_0": document.add_accessor(uvs.astype(np.float32), target=ARRAY_BUFFER),
        "JOINTS_0": document.add_accessor(joints, target=ARRAY_BUFFER),
        "WEIGHTS_0": document.add_accessor(mesh.weights.astype(np.float32), target=ARRAY_BUFFER),
    }
    indices_accessor = document.add_accessor(
        mesh.indices.astype(np.uint32).reshape(-1, 1), target=ELEMENT_ARRAY_BUFFER
    )
    ibm_accessor = document.add_accessor(ibm)

    # ---- material, mesh, skin, node --------------------------------------
    material = material or GarmentMaterial(name=name)
    material_index = document.add_material(material.to_gltf())
    _register_vrm0_material(document, info, material_index)

    primitive = {
        "attributes": attributes,
        "indices": indices_accessor,
        "material": material_index,
        "mode": 4,
    }
    mesh_index = document.add_mesh([primitive], name=name)
    skin_index = document.add_skin(joint_nodes, ibm_accessor, skeleton=info.humanoid_bones.get("hips"))
    node_index = document.add_node({"name": name, "mesh": mesh_index, "skin": skin_index})

    _register_first_person(document, info, node_index, mesh_index)

    return AttachResult(
        node_index=node_index,
        mesh_index=mesh_index,
        skin_index=skin_index,
        material_index=material_index,
        joint_nodes=joint_nodes,
        vertex_count=mesh.vertex_count,
        triangle_count=mesh.triangle_count,
    )


def _register_vrm0_material(document: GltfDocument, info: VrmInfo, material_index: int) -> None:
    """VRM 0.x requires materialProperties to stay aligned with materials."""
    if info.spec is not VrmSpec.VRM0:
        return
    block = document.extension(VRM0_EXTENSION)
    if block is None:
        return
    properties = block.setdefault("materialProperties", [])
    if not isinstance(properties, list):
        return
    material = document.materials[material_index]
    while len(properties) < material_index:
        properties.append({"name": "", "shader": "VRM_USE_GLTFSHADER"})
    properties.append(
        {
            "name": material.get("name", "Garment"),
            # Defer to the glTF PBR material rather than inventing MToon params.
            "shader": "VRM_USE_GLTFSHADER",
            "renderQueue": 2000,
            "floatProperties": {},
            "vectorProperties": {},
            "textureProperties": {},
            "keywordMap": {},
            "tagMap": {},
        }
    )


def _register_first_person(document: GltfDocument, info: VrmInfo, node_index: int, mesh_index: int) -> None:
    """Annotate the garment so first-person rendering does not hide it."""
    if info.spec is VrmSpec.VRM1:
        block = document.extension(VRM1_EXTENSION)
        if block is None:
            return
        first_person = block.setdefault("firstPerson", {})
        annotations = first_person.setdefault("meshAnnotations", [])
        if isinstance(annotations, list):
            annotations.append({"node": node_index, "type": "auto"})
    else:
        block = document.extension(VRM0_EXTENSION)
        if block is None:
            return
        first_person = block.setdefault("firstPerson", {})
        annotations = first_person.setdefault("meshAnnotations", [])
        if isinstance(annotations, list):
            annotations.append({"mesh": mesh_index, "firstPersonFlag": "Auto"})


def set_title(document: GltfDocument, info: VrmInfo, title: str) -> None:
    """Rename the derived model so wardrobes stay distinguishable in a viewer."""
    if info.spec is VrmSpec.VRM1:
        block = document.extension(VRM1_EXTENSION) or {}
        meta = block.setdefault("meta", {})
        meta["name"] = title
    else:
        block = document.extension(VRM0_EXTENSION) or {}
        meta = block.setdefault("meta", {})
        meta["title"] = title


def tag_derived(document: GltfDocument, *, source_hash: str | None, look_id: str, generator: str) -> None:
    """Record provenance in glTF ``extras`` so a derived VRM is traceable."""
    extras = document.gltf.setdefault("extras", {})
    extras["wardrobeForge"] = {
        "lookId": look_id,
        "sourceAvatarSha256": source_hash,
        "generator": generator,
    }
    asset = document.gltf.setdefault("asset", {})
    asset["generator"] = generator


__all__ = ["GarmentMaterial", "AttachResult", "AttachError", "attach_garment", "set_title", "tag_derived"]
