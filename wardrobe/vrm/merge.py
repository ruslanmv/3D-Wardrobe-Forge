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
    borrow_toon_shading(document, info, material_index, material.base_color)

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


#: MToon texture slots. A borrowed material keeps none of them: they are laid out for
#: the avatar's own UVs, and the garment's UVs are a plain cylinder unwrap.
_VRM0_TEXTURE_KEYWORDS = {"_NORMALMAP", "_ALPHATEST_ON", "_ALPHABLEND_ON", "_ALPHAPREMULTIPLY_ON"}
_SHADE_FACTOR = 0.72


def _linear_to_srgb(channel: float) -> float:
    channel = min(max(float(channel), 0.0), 1.0)
    return 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055


def _is_mtoon_vrm0(entry: dict) -> bool:
    return isinstance(entry, dict) and str(entry.get("shader", "")).startswith("VRM/MToon")


def _pick_source(names: list[str], candidates: list[int]) -> int | None:
    """Prefer the avatar's own clothing — cloth, not skin, is what a garment should shade like."""
    for index in candidates:
        if "_CLOTH" in names[index].upper():
            return index
    return candidates[0] if candidates else None


def borrow_toon_shading(
    document: GltfDocument, info: VrmInfo, material_index: int, base_color: tuple[float, ...]
) -> str | None:
    """Shade the garment the way the avatar's own clothes are shaded. Returns the source's name.

    A garment used to be a plain glTF PBR material: lit like a product shot, and
    visibly foreign on an anime avatar whose body, hair and clothes are all
    cel-shaded MToon. Rather than invent MToon parameters, this *borrows* them from
    a material the avatar already has — its toon ramp, shade shift, rim and outline
    — and puts the garment's colour in place of the texture. A model with no MToon
    material keeps the PBR one, exactly as before.
    """
    materials = document.materials
    names = [str(m.get("name") or "") for m in materials]

    if info.spec is VrmSpec.VRM1:
        candidates = [
            i for i, m in enumerate(materials)
            if i != material_index and "VRMC_materials_mtoon" in (m.get("extensions") or {})
        ]
        source = _pick_source(names, candidates)
        if source is None:
            return None
        mtoon = {
            key: value
            for key, value in materials[source]["extensions"]["VRMC_materials_mtoon"].items()
            if not key.endswith("Texture")
        }
        mtoon["shadeColorFactor"] = [float(c) * _SHADE_FACTOR for c in base_color[:3]]
        target = materials[material_index]
        target.setdefault("extensions", {})["VRMC_materials_mtoon"] = mtoon
        target["alphaMode"] = "OPAQUE"
        document.declare_extension("VRMC_materials_mtoon")
        return names[source]

    block = document.extension(VRM0_EXTENSION)
    properties = (block or {}).get("materialProperties")
    if not isinstance(properties, list) or material_index >= len(properties):
        return None
    candidates = [i for i, entry in enumerate(properties) if i != material_index and _is_mtoon_vrm0(entry)]
    source = _pick_source(names, candidates) if all(i < len(names) for i in candidates) else None
    if source is None:
        return None

    borrowed = properties[source]
    # VRM 0.x stores colours gamma-encoded; the plan's colour is linear.
    color = [_linear_to_srgb(c) for c in base_color[:3]]
    floats = dict(borrowed.get("floatProperties") or {})
    floats.update({"_BlendMode": 0, "_SrcBlend": 1, "_DstBlend": 0, "_ZWrite": 1})
    vectors = {
        key: value
        for key, value in (borrowed.get("vectorProperties") or {}).items()
        if key in {"_OutlineColor", "_EmissionColor"}
    }
    vectors["_Color"] = [*color, 1.0]
    vectors["_ShadeColor"] = [c * _SHADE_FACTOR for c in color] + [1.0]
    properties[material_index] = {
        "name": names[material_index],
        "shader": borrowed.get("shader", "VRM/MToon"),
        "renderQueue": 2000,
        "floatProperties": floats,
        "vectorProperties": vectors,
        "textureProperties": {},
        "keywordMap": {
            key: value for key, value in (borrowed.get("keywordMap") or {}).items()
            if key not in _VRM0_TEXTURE_KEYWORDS
        },
        "tagMap": {"RenderType": "Opaque"},
    }
    return names[source]


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
