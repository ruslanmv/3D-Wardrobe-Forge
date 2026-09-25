"""Synthetic VRM builder.

Wardrobe Forge's acceptance criteria require several avatars with *different
body proportions*. Shipping third-party VRM binaries would drag licensing and
repository weight along with it, so instead we generate humanoid fixtures
procedurally: a real skeleton, a real skinned body mesh, and real VRM 0.x /
1.0 extension blocks.

These fixtures are also genuinely useful outside tests — they are the
calibration bodies the fitting stage is tuned against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate
from wardrobe.geometry.procedural import Ring, loft, sweep
from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument
from wardrobe.vrm.skinning import BoneSegment, bind_mesh

GENERATOR = "3D-Wardrobe-Forge fixture builder"

#: VRM 1.0 preset expressions every fixture declares, so the acceptance
#: criteria can check that a derived look preserves them.
EXPRESSION_PRESETS = (
    "happy", "angry", "sad", "relaxed", "surprised",
    "aa", "ih", "ou", "ee", "oh", "blink",
)


@dataclass(slots=True)
class BodyProportions:
    """Parameters that make each calibration body meaningfully different."""

    name: str = "calibration-medium"
    height: float = 1.62
    shoulder_width: float = 0.34
    hip_width: float = 0.32
    chest_width: float = 0.30
    depth: float = 0.21
    leg_ratio: float = 0.52
    arm_ratio: float = 0.44
    #: Modification permission written into the VRM metadata.
    modification: str = "allowModificationRedistribution"
    extras: dict = field(default_factory=dict)


#: A deliberately varied set: the same garment must work on all of them.
CALIBRATION_BODIES: tuple[BodyProportions, ...] = (
    BodyProportions(name="calibration-a-petite", height=1.48, shoulder_width=0.29, hip_width=0.28,
                    chest_width=0.26, depth=0.18, leg_ratio=0.50, arm_ratio=0.42),
    BodyProportions(name="calibration-b-medium", height=1.62, shoulder_width=0.34, hip_width=0.32,
                    chest_width=0.30, depth=0.21, leg_ratio=0.52, arm_ratio=0.44),
    BodyProportions(name="calibration-c-tall", height=1.83, shoulder_width=0.42, hip_width=0.34,
                    chest_width=0.38, depth=0.25, leg_ratio=0.55, arm_ratio=0.46),
    BodyProportions(name="calibration-d-broad", height=1.70, shoulder_width=0.46, hip_width=0.44,
                    chest_width=0.44, depth=0.30, leg_ratio=0.48, arm_ratio=0.43),
)


def skeleton_positions(body: BodyProportions) -> dict[str, np.ndarray]:
    """Rest-pose (T-pose) world positions for every humanoid bone."""
    h = body.height
    leg = h * body.leg_ratio
    arm = h * body.arm_ratio
    hips_y = leg + h * 0.02
    half_shoulder = body.shoulder_width * 0.5

    # Torso landmarks interpolate between the hips and the (absolute) neck so
    # that a long-legged body does not end up with a compressed torso.
    neck_y = h * 0.82
    positions: dict[str, np.ndarray] = {
        "hips": np.array([0.0, hips_y, 0.0]),
        "spine": np.array([0.0, hips_y + (neck_y - hips_y) * 0.26, 0.0]),
        "chest": np.array([0.0, hips_y + (neck_y - hips_y) * 0.52, 0.0]),
        "upperChest": np.array([0.0, hips_y + (neck_y - hips_y) * 0.74, 0.0]),
        "neck": np.array([0.0, neck_y, 0.0]),
        "head": np.array([0.0, h * 0.86, 0.0]),
    }

    shoulder_y = hips_y + (neck_y - hips_y) * 0.88
    for side, sign in (("left", 1.0), ("right", -1.0)):
        positions[f"{side}Shoulder"] = np.array([sign * half_shoulder * 0.35, shoulder_y, 0.0])
        positions[f"{side}UpperArm"] = np.array([sign * half_shoulder, shoulder_y, 0.0])
        positions[f"{side}LowerArm"] = np.array([sign * (half_shoulder + arm * 0.45), shoulder_y, 0.0])
        positions[f"{side}Hand"] = np.array([sign * (half_shoulder + arm * 0.88), shoulder_y, 0.0])

        hip_offset = sign * body.hip_width * 0.27
        positions[f"{side}UpperLeg"] = np.array([hip_offset, hips_y - h * 0.025, 0.0])
        positions[f"{side}LowerLeg"] = np.array([hip_offset, hips_y * 0.52, 0.0])
        positions[f"{side}Foot"] = np.array([hip_offset, h * 0.045, 0.0])
        positions[f"{side}Toes"] = np.array([hip_offset, h * 0.018, h * 0.06])

    return positions


#: parent -> child bone names, used to build the node hierarchy.
SKELETON_TREE: dict[str, tuple[str, ...]] = {
    "hips": ("spine", "leftUpperLeg", "rightUpperLeg"),
    "spine": ("chest",),
    "chest": ("upperChest",),
    "upperChest": ("neck", "leftShoulder", "rightShoulder"),
    "neck": ("head",),
    "head": (),
    "leftShoulder": ("leftUpperArm",),
    "leftUpperArm": ("leftLowerArm",),
    "leftLowerArm": ("leftHand",),
    "leftHand": (),
    "rightShoulder": ("rightUpperArm",),
    "rightUpperArm": ("rightLowerArm",),
    "rightLowerArm": ("rightHand",),
    "rightHand": (),
    "leftUpperLeg": ("leftLowerLeg",),
    "leftLowerLeg": ("leftFoot",),
    "leftFoot": ("leftToes",),
    "leftToes": (),
    "rightUpperLeg": ("rightLowerLeg",),
    "rightLowerLeg": ("rightFoot",),
    "rightFoot": ("rightToes",),
    "rightToes": (),
}


def build_body_mesh(body: BodyProportions, positions: dict[str, np.ndarray]) -> Mesh:
    """A simple but complete humanoid body shell in world space."""
    h = body.height
    torso_half_w = body.chest_width * 0.5
    torso_half_d = body.depth * 0.5
    hip_half_w = body.hip_width * 0.5

    torso = loft(
        [
            Ring(float(positions["hips"][1]) - h * 0.02, hip_half_w, torso_half_d * 0.95),
            Ring(float(positions["spine"][1]), hip_half_w * 0.86, torso_half_d * 0.85),
            Ring(float(positions["chest"][1]), torso_half_w * 0.98, torso_half_d * 0.95),
            Ring(float(positions["upperChest"][1]), torso_half_w, torso_half_d),
            Ring(float(positions["neck"][1]), torso_half_w * 0.42, torso_half_d * 0.42),
        ],
        segments=20,
        cap_bottom=True,
        name="torso",
    )

    # The head bone sits at the base of the skull, so the skull volume is
    # centred above it.
    head_radius = h * 0.075
    head_y = float(positions["head"][1]) + head_radius * 0.75
    head = loft(
        [
            Ring(head_y - head_radius, head_radius * 0.55, head_radius * 0.55),
            Ring(head_y - head_radius * 0.4, head_radius * 0.95, head_radius),
            Ring(head_y + head_radius * 0.4, head_radius * 0.95, head_radius),
            Ring(head_y + head_radius, head_radius * 0.45, head_radius * 0.45),
        ],
        segments=20,
        cap_top=True,
        cap_bottom=True,
        name="head",
    )

    sections: list[Mesh] = [torso, head]
    arm_radius = max(h * 0.028, 0.02)
    leg_radius = max(body.hip_width * 0.21, 0.04)

    for side in ("left", "right"):
        sections.append(
            sweep(
                np.array(
                    [positions[f"{side}UpperArm"], positions[f"{side}LowerArm"], positions[f"{side}Hand"]]
                ),
                [arm_radius * 1.15, arm_radius, arm_radius * 0.8],
                segments=10,
                name=f"arm-{side}",
            )
        )
        sections.append(
            sweep(
                np.array(
                    [positions[f"{side}UpperLeg"], positions[f"{side}LowerLeg"], positions[f"{side}Foot"]]
                ),
                [leg_radius, leg_radius * 0.72, leg_radius * 0.5],
                segments=10,
                name=f"leg-{side}",
            )
        )

    return concatenate(sections)


def _normalize_to_height(positions: dict[str, np.ndarray], mesh: Mesh, target_height: float) -> float:
    """Scale skeleton and mesh together so the fixture's real height is exact.

    Without this the declared height is only approximately the rendered height,
    which would quietly bias every garment length computed from it.
    """
    low, high = mesh.bounds()
    current = float(high[1] - low[1])
    if current <= 1e-6:
        raise ValueError("generated body mesh has no height")

    scale = target_height / current
    offset = float(low[1]) * scale  # drop the feet onto y = 0

    mesh.positions = (mesh.positions * scale).astype(np.float32)
    mesh.positions[:, 1] -= offset
    for name, position in positions.items():
        scaled = position * scale
        scaled[1] -= offset
        positions[name] = scaled
    return scale


def build_vrm(body: BodyProportions, *, spec: str = "VRM1", mesh_builder=None) -> bytes:
    """Return a complete, self-contained VRM as GLB bytes.

    ``mesh_builder(body, positions) -> Mesh`` replaces the calibration body's
    surface and keeps everything else — skeleton, skinning, VRM blocks — as it
    is: the fashion-fit forms (``wardrobe.vrm.fashion_body``) are the same rig
    under a better-shaped skin. Absent, the calibration body, byte for byte.
    """
    if spec not in {"VRM0", "VRM1"}:
        raise ValueError("spec must be 'VRM0' or 'VRM1'")

    positions = skeleton_positions(body)
    mesh = (mesh_builder or build_body_mesh)(body, positions)
    _normalize_to_height(positions, mesh, body.height)
    bone_names = list(SKELETON_TREE)

    # ---- nodes (local translations relative to parent) -------------------
    parent_of: dict[str, str] = {}
    for parent, children in SKELETON_TREE.items():
        for child in children:
            parent_of[child] = parent

    node_index = {name: index for index, name in enumerate(bone_names)}
    nodes: list[dict] = []
    for name in bone_names:
        parent = parent_of.get(name)
        origin = positions[parent] if parent else np.zeros(3)
        nodes.append(
            {
                "name": name,
                "translation": [float(v) for v in (positions[name] - origin)],
                "children": [node_index[c] for c in SKELETON_TREE[name]] or None,
            }
        )
    for node in nodes:
        if node["children"] is None:
            node.pop("children")

    gltf = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "scene": 0,
        "scenes": [{"nodes": [node_index["hips"]]}],
        "nodes": nodes,
        "buffers": [{"byteLength": 0}],
    }
    document = GltfDocument(gltf, b"")

    # ---- skinned body mesh ----------------------------------------------
    segments = [
        BoneSegment(
            name=name,
            node=node_index[name],
            head=positions[name],
            tail=(
                positions[SKELETON_TREE[name][0]]
                if SKELETON_TREE.get(name)
                else positions[name] + np.array([0.0, body.height * 0.04, 0.0])
            ),
        )
        for name in bone_names
    ]
    # A builder may mark its torso: those vertices never take arm bones, so posing
    # the arms does not drag the side of her chest with them. The calibration body
    # marks none and is bound as it always was.
    bind_mesh(mesh, segments, falloff=2.0, torso=mesh.metadata.get("bindTorso"))

    joint_nodes = [segment.node for segment in segments]
    ibm = np.zeros((len(joint_nodes), 16), dtype=np.float32)
    for row, name in enumerate(bone_names):
        matrix = np.eye(4)
        matrix[:3, 3] = positions[name]
        ibm[row] = np.linalg.inv(matrix).T.reshape(-1).astype(np.float32)

    material_index = document.add_material(
        {
            "name": "Body",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.93, 0.80, 0.72, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
        }
    )
    primitive = {
        "attributes": {
            "POSITION": document.add_accessor(mesh.positions, target=ARRAY_BUFFER, include_bounds=True),
            "NORMAL": document.add_accessor(mesh.normals, target=ARRAY_BUFFER),
            "TEXCOORD_0": document.add_accessor(mesh.uvs, target=ARRAY_BUFFER),
            "JOINTS_0": document.add_accessor(mesh.joints, target=ARRAY_BUFFER),
            "WEIGHTS_0": document.add_accessor(mesh.weights, target=ARRAY_BUFFER),
        },
        "indices": document.add_accessor(mesh.indices.reshape(-1, 1), target=ELEMENT_ARRAY_BUFFER),
        "material": material_index,
        "mode": 4,
    }
    mesh_index = document.add_mesh([primitive], name="Body")
    skin_index = document.add_skin(joint_nodes, document.add_accessor(ibm), skeleton=node_index["hips"])
    body_node = document.add_node({"name": "BodyMesh", "mesh": mesh_index, "skin": skin_index})

    # ---- VRM extension block --------------------------------------------
    if spec == "VRM1":
        document.gltf.setdefault("extensions", {})["VRMC_vrm"] = _vrm1_block(body, node_index, body_node)
        document.declare_extension("VRMC_vrm", required=True)
    else:
        document.gltf.setdefault("extensions", {})["VRM"] = _vrm0_block(body, node_index, mesh_index)
        document.declare_extension("VRM", required=True)

    return document.to_bytes()


def _vrm1_block(body: BodyProportions, node_index: dict[str, int], body_node: int) -> dict:
    return {
        "specVersion": "1.0",
        "meta": {
            "name": body.name,
            "version": "1.0",
            "authors": ["3D-Wardrobe-Forge"],
            "licenseUrl": "https://vrm.dev/licenses/1.0/",
            "avatarPermission": "everyone",
            "allowExcessivelyViolentUsage": False,
            "allowExcessivelySexualUsage": False,
            "commercialUsage": "corporation",
            "allowPoliticalOrReligiousUsage": False,
            "allowAntisocialOrHateUsage": False,
            "creditNotation": "unnecessary",
            "allowRedistribution": True,
            "modification": body.modification,
        },
        "humanoid": {
            "humanBones": {name: {"node": index} for name, index in node_index.items()}
        },
        "firstPerson": {"meshAnnotations": [{"node": body_node, "type": "auto"}]},
        "expressions": {
            "preset": {
                name: {"isBinary": False, "morphTargetBinds": [], "materialColorBinds": [],
                       "textureTransformBinds": []}
                for name in EXPRESSION_PRESETS
            }
        },
        "lookAt": {"type": "bone", "offsetFromHeadBone": [0.0, 0.06, 0.0]},
    }


def _vrm0_block(body: BodyProportions, node_index: dict[str, int], mesh_index: int) -> dict:
    modification_to_license = {
        "prohibited": "CC_BY_ND",
        "allowModification": "Redistribution_Prohibited",
        "allowModificationRedistribution": "CC0",
    }
    return {
        "exporterVersion": GENERATOR,
        "specVersion": "0.0",
        "meta": {
            "title": body.name,
            "version": "1.0",
            "author": "3D-Wardrobe-Forge",
            "allowedUserName": "Everyone",
            "violentUssageName": "Disallow",
            "sexualUssageName": "Disallow",
            "commercialUssageName": "Allow",
            "licenseName": modification_to_license.get(body.modification, "CC0"),
        },
        "humanoid": {
            "humanBones": [{"bone": name, "node": index} for name, index in node_index.items()]
        },
        "firstPerson": {
            "firstPersonBone": node_index["head"],
            "meshAnnotations": [{"mesh": mesh_index, "firstPersonFlag": "Auto"}],
        },
        "blendShapeMaster": {"blendShapeGroups": []},
        "secondaryAnimation": {"boneGroups": [], "colliderGroups": []},
        "materialProperties": [{"name": "Body", "shader": "VRM_USE_GLTFSHADER", "renderQueue": 2000}],
    }


__all__ = ["BodyProportions", "CALIBRATION_BODIES", "skeleton_positions", "build_body_mesh", "build_vrm"]
