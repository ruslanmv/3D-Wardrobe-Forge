"""RB4. A reference body as a VRM the pipeline can dress: skinned, with a skeleton from her joints.

The surface is the reference body's own (``wardrobe.anatomy.reference``), unchanged; this only
binds it. Joints come from the template's joint helpers, which the calibration moved with her,
so her hips are where her hips are rather than where a height formula puts them. The arms are
raised from the template's rest pose to the T-pose a VRM is expected to be bound in (``t_pose``);
nothing else moves, so she is measured in the rest pose and dressed in the same trunk.

The VRM records what the body is and what it is not in ``extras.wardrobeAnatomy``: the size, the
survey it is calibrated to, the template's provenance and ``UNMODELLED`` — a report that dresses
her can quote that instead of implying more than was built.
"""

from __future__ import annotations

import json

import numpy as np

from wardrobe.anatomy import reference as R
from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.build import BodyProportions, build_vrm
from wardrobe.vrm.document import GltfDocument

#: VRM humanoid bone -> MakeHuman joint helper.
BONES = {
    "hips": "joint-pelvis",
    "spine": "joint-spine-3",
    "chest": "joint-spine-2",
    "upperChest": "joint-spine-1",
    "neck": "joint-neck",
    "head": "joint-head",
    **{
        f"{s}{b}": f"joint-{c}-{j}"
        for s, c in (("left", "l"), ("right", "r"))
        for b, j in (
            ("Shoulder", "clavicle"),
            ("UpperArm", "shoulder"),
            ("LowerArm", "elbow"),
            ("Hand", "hand"),
            ("UpperLeg", "upper-leg"),
            ("LowerLeg", "knee"),
            ("Foot", "ankle"),
            ("Toes", "foot-2"),
        )
    },
}


def skeleton(joints: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {bone: np.asarray(joints[helper], dtype=np.float64) for bone, helper in BONES.items()}


#: The arm's reach from its bone chain, and the band over which a vertex's membership fades out.
ARM_REACH_M = 0.075
ARM_FADE_M = 0.02
#: How far inside the shoulder joint's line the arm begins, and the band it fades in over.
ARM_INSET_M = 0.02
ARM_INSET_FADE_M = 0.03
#: How far down the upper arm the rotation into the T-pose ramps from none to all.
ARM_RAMP_M = 0.08


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _hand(V: np.ndarray, joints: dict[str, np.ndarray], side: str) -> np.ndarray:
    """Her hand: within 25 cm of the wrist, beyond it from the elbow, and no more than 10 cm in toward
    her — her thigh, the only other surface near a hanging hand, is further in than that in every
    size and pose."""
    sign = 1.0 if side == "l" else -1.0
    hand, elbow = joints[f"joint-{side}-hand"], joints[f"joint-{side}-elbow"]
    near = np.linalg.norm(V - hand, axis=1) < 0.25
    near &= np.linalg.norm(V - elbow, axis=1) > float(np.linalg.norm(hand - elbow))
    return near & (sign * V[:, 0] > sign * hand[0] - 0.10)


def _fingertip(V: np.ndarray, joints: dict[str, np.ndarray], side: str) -> np.ndarray:
    """The far end of her hand: its vertex furthest from the elbow.

    The chain once ran on 20 cm straight along the forearm. MakeHuman's rest-pose hand points its
    fingers forward, up to 14 cm in front of the wrist, so they fell outside the arm's reach, stayed
    bound to her trunk, and drew strips out to the T-pose when a viewer lowered the arms.
    """
    hand = _hand(V, joints, side)
    if not hand.any():
        return joints[f"joint-{side}-hand"]
    candidates = V[hand]
    return candidates[np.argmax(np.linalg.norm(candidates - joints[f"joint-{side}-elbow"], axis=1))]


def _chain_distance(V: np.ndarray, joints: dict[str, np.ndarray], side: str) -> np.ndarray:
    chain = [joints[f"joint-{side}-{j}"] for j in ("shoulder", "elbow", "hand")]
    chain.append(_fingertip(V, joints, side))
    best = np.full(V.shape[0], np.inf)
    for a, b in zip(chain[:-1], chain[1:], strict=True):
        ab = b - a
        t = np.clip(((V - a) @ ab) / float(ab @ ab), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(V - (a + t[:, None] * ab), axis=1))
    return best


def arm_weight(V: np.ndarray, joints: dict[str, np.ndarray], side: str) -> np.ndarray:
    """How much each vertex belongs to one arm, 0 to 1, varying smoothly over her surface.

    Near the shoulder-elbow-hand chain and outside the shoulder joint's line. A yes/no mask turned
    arm vertices while their trunk neighbours stayed put, and the T-posed surface folded through
    itself at the back of each armpit (4 edge crossings on the median body); a weight that fades
    over ``ARM_FADE_M`` and ``ARM_INSET_FADE_M`` turns the seam between them gradually.
    """
    sign = 1.0 if side == "l" else -1.0
    near = _smoothstep((ARM_REACH_M + ARM_FADE_M / 2 - _chain_distance(V, joints, side)) / ARM_FADE_M)
    line = sign * joints[f"joint-{side}-shoulder"][0] - ARM_INSET_M
    outside = _smoothstep((sign * V[:, 0] - line + ARM_INSET_FADE_M / 2) / ARM_INSET_FADE_M)
    # The fade is for the seam with her trunk. Her hand is wholly arm: spread fingers lie up to 7 cm
    # off the bone line, and fading them turned them by part of the arm's angle, off her hand.
    return np.maximum(near * outside, _hand(V, joints, side).astype(float))


def arm_mask(V: np.ndarray, joints: dict[str, np.ndarray]) -> np.ndarray:
    """Vertices of her arms (more arm than trunk), for binding them to the arm bones."""
    return (arm_weight(V, joints, "l") > 0.5) | (arm_weight(V, joints, "r") > 0.5)


def t_pose(V: np.ndarray, J: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Raise her arms from the template's rest pose (about 45 degrees down) to the T-pose VRM expects.

    Exported in the template's pose, the viewer's relaxed-pose step bent the arms down a second
    time and they folded into rods in front of her. Each arm turns about its shoulder joint in her
    frontal plane until shoulder-to-hand is level. A vertex turns by the arm's angle times its
    ``arm_weight`` times a ramp over the first ``ARM_RAMP_M`` of the upper arm, so the armpit and
    shoulder blend rather than tear or fold. Her trunk does not move, so every trunk measurement
    and landmark is the same before and after.
    """
    V = V.copy()
    J = {k: v.copy() for k, v in J.items()}
    for side, sign in (("l", 1.0), ("r", -1.0)):
        shoulder, hand = J[f"joint-{side}-shoulder"], J[f"joint-{side}-hand"]
        d = hand - shoulder
        theta = np.arctan2(-d[1], sign * d[0])  # how far below level the arm points, in her frontal plane
        elbow = J[f"joint-{side}-elbow"]
        axis = (elbow - shoulder) / np.linalg.norm(elbow - shoulder)
        w = arm_weight(V, J, side)
        mine = w > 0
        ramp = _smoothstep(((V[mine] - shoulder) @ axis) / ARM_RAMP_M)
        V[mine] = _turn_many(V[mine], shoulder, sign * theta * ramp * w[mine])
        for name in ("elbow", "hand"):
            J[f"joint-{side}-{name}"] = _turn_many(
                J[f"joint-{side}-{name}"][None], shoulder, np.array([sign * theta])
            )[0]
    return V, J


def _turn_many(points: np.ndarray, pivot: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """Rotate each point about the z axis through ``pivot`` by its own angle."""
    c, s = np.cos(angles), np.sin(angles)
    rel = points - pivot
    out = rel.copy()
    out[:, 0] = c * rel[:, 0] - s * rel[:, 1]
    out[:, 1] = s * rel[:, 0] + c * rel[:, 1]
    return out + pivot


def reference_surface(size_id: str):
    """(vertices, triangles, joints, measured) of a size in the VRM's T-pose; measured in her rest pose."""
    V, T, J, measured = R.reference_body(size_id)
    V, J = t_pose(V, J)
    return V, T, J, measured


def build_reference_vrm(size_id: str, *, spec: str = "VRM1") -> bytes:
    V, T, J, measured = reference_surface(size_id)
    record = R.reference_bodies()["bodies"][size_id]
    mesh = Mesh(
        positions=V.astype(np.float32), indices=T.reshape(-1).astype(np.uint32), metadata={"section": "body"}
    )
    mesh.compute_normals()
    # Cylindrical UVs round her vertical axis: the body carries no texture, but the format wants them.
    mesh.uvs = np.column_stack(
        [(np.arctan2(V[:, 0], V[:, 2]) / (2 * np.pi)) + 0.5, V[:, 1] / max(float(V[:, 1].max()), 1e-6)]
    ).astype(np.float32)
    mesh.metadata["bindTorso"] = ~arm_mask(V, J)

    def builder(_body, _positions):
        return mesh

    body = BodyProportions(name=size_id, height=float(V[:, 1].max()))
    data = build_vrm(body, spec=spec, mesh_builder=builder, skeleton=skeleton(J))
    document = GltfDocument.from_bytes(data)
    extras = document.gltf.setdefault("extras", {})
    extras["wardrobeAnatomy"] = {
        "sizeId": size_id,
        "kind": "anatomical-reference-body",
        "survey": "ANSUR II female, age 21+ (assets/anatomy/reference-sizes.json)",
        "template": json.loads((R.ROOT / "assets" / "anatomy" / "makehuman-provenance.json").read_text())[
            "commit"
        ],
        "measuredMm": {k: round(v, 1) for k, v in measured.values.items()},
        "landmarks": measured.landmarks,
        "modifiers": record["modifiers"],
        "unmodelled": R.UNMODELLED,
    }
    return document.to_bytes()


__all__ = [
    "BONES",
    "arm_mask",
    "arm_weight",
    "build_reference_vrm",
    "reference_surface",
    "skeleton",
    "t_pose",
]
