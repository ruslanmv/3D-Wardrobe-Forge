"""SA2. How a reference body moves: MakeHuman's skin weights on the VRM's bones, and the bind they need.

**The defect this replaces.** The reference VRMs were bound with a yes/no split (``bindTorso``): a
vertex was arm or trunk, never part of each. When a viewer lowered the arms, the arm side of the
shoulder turned and the trunk side stayed where the T-pose had left it: a ridge over each shoulder
that read as a separate ball joint, skin folded through itself under it, and the armpit torn
between the two. Posed back to the very angle the body was sculpted at, the median body had 676
folds sharper than 60 degrees and 458 crossing edges within 17 cm of the shoulders, where the
sculpt has none. It was the rig, not the mesh.

**The weights.** MakeHuman's artists painted weights for this mesh (CC0; imported by
``tools/anatomy/import_makehuman_rig.py``): spine, breast, clavicle, a deltoid bone
(``shoulder01``), two upper-arm bones, and so on to the fingers, graded across the shoulder, the
armpit and the upper back. A VRM has fewer bones, so each MakeHuman bone's weight goes to the VRM
bone whose joint its head sits on, or, when its head is between joints (a twist bone, the deltoid
bone, a spine segment the VRM does not have), to its parent's. That puts ``shoulder01`` on the
clavicle, as MakeHuman's own hierarchy does; bound to the upper arm instead it measured no better
in any test pose. Toe bones go to the VRM's toes. The weights are on the template's base mesh and
are carried to the subdivided surface by the same linear subdivision as its positions, whose rows
sum to one, so they stay a partition of unity and stay smooth; four per vertex are kept, as glTF
holds, and the dropped share is at most 8 % on any vertex (0.9 % at the 99th percentile).

**The bind.** A VRM is bound in the T-pose, and every viewer poses it with linear blend skinning
from there. The body was sculpted with her arms 47 degrees below level. Turning the arms up with
the same weights and letting the viewer turn them down again does not come back: blended
rotations shrink the skin between bones each way, 12 mm on the median shoulder. So the T-pose is
solved the other way round (``t_pose``): each vertex's T-pose position is the one the viewer's own
skinning carries exactly onto the sculpt when the arms are lowered to the sculpted angle. The
sculpt is reproduced to rounding in every viewer, with no corrective a viewer would have to know
how to drive, and the poses near it — the relaxed pose the Studio and the gallery show is 21
degrees further down — start from the right surface.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from wardrobe.anatomy import template as TM
from wardrobe.vrm.build import SKELETON_TREE

RIG_PATH = TM.ROOT / "assets" / "anatomy" / "makehuman-rig.npz"

#: The VRM's bones, in the order the skin lists them (``wardrobe.vrm.build``).
VRM_BONES: tuple[str, ...] = tuple(SKELETON_TREE)
PARENT = {child: parent for parent, children in SKELETON_TREE.items() for child in children}

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
ARM_CHAIN = {s: tuple(f"{s}{b}" for b in ("UpperArm", "LowerArm", "Hand")) for s in ("left", "right")}
INFLUENCES = 4


@lru_cache(maxsize=1)
def _rig() -> dict:
    data = np.load(RIG_PATH)
    return {k: data[k] for k in data.files}


def vrm_bone_of(bone: str) -> str:
    """The VRM bone a MakeHuman bone's weight goes to (see the module docstring)."""
    rig = _rig()
    names = [str(n) for n in rig["bone_names"]]
    if bone.startswith("toe"):
        return "leftToes" if bone.endswith(".L") else "rightToes"
    by_joint = {joint: vrm for vrm, joint in BONES.items()}
    k = names.index(bone)
    while k >= 0:
        joint = str(rig["bone_head_joint"][k])
        if joint in by_joint:
            return by_joint[joint]
        k = int(rig["bone_parent"][k])
    return "hips"


@lru_cache(maxsize=1)
def base_weights() -> np.ndarray:
    """(template body vertices, VRM bones): each row sums to 1."""
    rig = _rig()
    names = [str(n) for n in rig["bone_names"]]
    column = np.array([VRM_BONES.index(vrm_bone_of(b)) for b in names])
    W = np.zeros((int(rig["body_count"]), len(VRM_BONES)))
    np.add.at(W, (rig["w_vertex"], column[rig["w_bone"]]), rig["w_value"].astype(np.float64))
    total = W.sum(axis=1, keepdims=True)
    if np.any(total <= 0):
        raise ValueError("a template vertex has no skin weight")
    return W / total


def _levels_for(count: int) -> int:
    t = TM.template()
    if count == t.body_count:
        return 0
    for levels in (1, 2, 3):
        if TM.subdivision(levels)[-1].count == count:
            return levels
    raise ValueError(f"{count} vertices is not the template subdivided 0-3 times")


@lru_cache(maxsize=3)
def skin(count: int) -> tuple[np.ndarray, np.ndarray]:
    """(joints, weights), each (count, 4), for the template subdivided to ``count`` vertices.

    ``joints`` index ``VRM_BONES``; each row of ``weights`` sums to 1.
    """
    W = base_weights()
    levels = _levels_for(count)
    for step in TM.subdivision(levels) if levels else ():
        out = np.zeros((step.count, W.shape[1]))
        np.add.at(out, step.rows, W[step.cols] * step.vals[:, None])
        W = out
    order = np.argsort(-W, axis=1, kind="stable")
    joints = order[:, :INFLUENCES]
    weights = np.take_along_axis(W, joints, axis=1)
    # Cut to four continuously: take the fifth-largest weight off each of the four kept. Keeping
    # the four largest as they are made a bone's weight jump from a few percent to nothing between
    # neighbouring vertices wherever five bones meet (the base of her neck: neck, upper chest, a
    # clavicle and both arms), and the solved T-pose kinked there: 88 folds sharper than 60
    # degrees. The fifth weight changes continuously over her surface, so the cut does too.
    fifth = np.take_along_axis(W, order[:, INFLUENCES : INFLUENCES + 1], axis=1)
    weights = np.maximum(weights - fifth, 0.0)
    weights /= weights.sum(axis=1, keepdims=True)
    return joints.astype(np.uint16), weights


def dense_weights(count: int) -> np.ndarray:
    """(count, VRM bones) from :func:`skin`: what the VRM carries, as one column per bone."""
    joints, weights = skin(count)
    out = np.zeros((count, len(VRM_BONES)))
    np.put_along_axis(out, joints.astype(np.int64), weights, axis=1)
    return out


def arm_angles(J: dict[str, np.ndarray]) -> dict[str, float]:
    """How far below level each arm points (radians, in her frontal plane), shoulder to hand."""
    out = {}
    for side, s, sign in (("left", "l", 1.0), ("right", "r", -1.0)):
        d = J[f"joint-{s}-hand"] - J[f"joint-{s}-shoulder"]
        out[side] = float(np.arctan2(-d[1], sign * d[0]))
    return out


def rotation(axis, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def sculpted_pose(J: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Normalized-bone rotations that lower a T-posed body's arms to the angle she was sculpted at."""
    a = arm_angles(J)
    return {
        "leftUpperArm": rotation((0, 0, 1), -a["left"]),
        "rightUpperArm": rotation((0, 0, 1), a["right"]),
    }


def bone_positions(J: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {bone: np.asarray(J[joint], dtype=np.float64) for bone, joint in BONES.items()}


def skinning_matrices(bind: dict[str, np.ndarray], pose: dict[str, np.ndarray]) -> np.ndarray:
    """(bones, 4, 4): what a viewer applies to a bound vertex for each bone, for normalized-bone
    rotations ``pose`` (bone -> 3x3, each in its parent's frame; absent is identity).

    The bones are bound unrotated, as ``wardrobe.vrm.build`` writes them, so this is what
    three-vrm does: world = parent world * translate(offset from parent) * rotate, then times the
    inverse bind, which is translate(-bind position).
    """
    world: dict[str, np.ndarray] = {}
    for bone in VRM_BONES:  # SKELETON_TREE lists parents before children
        parent = PARENT.get(bone)
        local = np.eye(4)
        local[:3, 3] = bind[bone] - (bind[parent] if parent else 0.0)
        local[:3, :3] = pose.get(bone, np.eye(3))
        world[bone] = (world[parent] if parent else np.eye(4)) @ local
    out = np.empty((len(VRM_BONES), 4, 4))
    for k, bone in enumerate(VRM_BONES):
        inverse_bind = np.eye(4)
        inverse_bind[:3, 3] = -bind[bone]
        out[k] = world[bone] @ inverse_bind
    return out


def pose_surface(
    V: np.ndarray,
    bind: dict[str, np.ndarray],
    pose: dict[str, np.ndarray],
    morph: np.ndarray | None = None,
    weights_of: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """A bound surface posed as a viewer poses it (linear blend skinning, morph added first).

    ``weights_of`` is another (joints, weights) to pose with, indexing ``VRM_BONES`` — a VRM's own,
    read back by ``wardrobe.anatomy.posecheck.read_vrm``; absent, the rig's.
    """
    joints, weights = weights_of if weights_of is not None else skin(V.shape[0])
    S = skinning_matrices(bind, pose)
    base = V if morph is None else V + morph
    out = np.zeros_like(base, dtype=np.float64)
    for k in range(INFLUENCES):
        Sk = S[joints[:, k].astype(np.int64)]
        out += weights[:, k, None] * (np.einsum("nij,nj->ni", Sk[:, :3, :3], base) + Sk[:, :3, 3])
    return out


def t_pose(V: np.ndarray, J: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """The T-pose a reference body is bound in: (surface, joints).

    The arm joints turn up about the shoulder in her frontal plane until shoulder-to-hand is level.
    The surface is solved, not turned: each vertex is put where the viewer's skinning, lowering
    the arms back to the sculpted angle (:func:`sculpted_pose`), carries it exactly onto ``V``.
    Per vertex that skinning is one affine map, the weighted sum of its bones' maps; its linear
    part is a blend of rotations about parallel axes, never singular, so the solve is exact.
    """
    J = {k: np.asarray(v, dtype=np.float64).copy() for k, v in J.items()}
    angles = arm_angles(J)
    TJ = dict(J)
    for side, s, sign in (("left", "l", 1.0), ("right", "r", -1.0)):
        shoulder = J[f"joint-{s}-shoulder"]
        up = rotation((0, 0, 1), sign * angles[side])
        for name in ("elbow", "hand"):
            TJ[f"joint-{s}-{name}"] = up @ (J[f"joint-{s}-{name}"] - shoulder) + shoulder
    return unskin(V, bone_positions(TJ), sculpted_pose(J)), TJ


def unskin(posed: np.ndarray, bind: dict[str, np.ndarray], pose: dict[str, np.ndarray]) -> np.ndarray:
    """The bound positions a viewer's skinning carries exactly onto ``posed`` in ``pose``.

    Per vertex the skinning is one affine map, the weighted sum of its bones' maps; this inverts
    it. Used for the T-pose (``t_pose``) and for the corrective morphs
    (``wardrobe.anatomy.correctives``), which are the posed corrections carried back to the bind.
    """
    S = skinning_matrices(bind, pose)
    joints, weights = skin(posed.shape[0])
    A = np.zeros((posed.shape[0], 3, 3))
    b = np.zeros((posed.shape[0], 3))
    for k in range(INFLUENCES):
        Sk = S[joints[:, k].astype(np.int64)]
        A += weights[:, k, None, None] * Sk[:, :3, :3]
        b += weights[:, k, None] * Sk[:, :3, 3]
    return np.linalg.solve(A, (posed - b)[..., None])[..., 0]


#: The arm poses a reference body is tested in (``wardrobe.anatomy.posecheck``) and rendered in
#: (``tools/anatomy/render_reference.py``): normalized-bone rotations from the T-pose, in degrees
#: about her own axes (x to her left, y up, z to her front), for her left side; the right mirrors.
#: "relaxed" is the Studio viewer's own (``apps/studio/js/viewer.js``: 1.18 rad, forearm 0.18).
TEST_POSES: dict[str, dict[str, tuple[tuple[str, float], ...]]] = {
    "sculpted": {},  # from the body's own arm angle: named_pose()
    "relaxed": {"UpperArm": (("z", -67.6),), "LowerArm": (("y", -10.3),)},
    "t-pose": {},
    "raised-sideways": {"UpperArm": (("z", 35.0),)},
    "raised-forward": {"UpperArm": (("z", -10.0), ("y", -85.0))},
    "lowered": {"UpperArm": (("z", -82.0),)},
    "rotated-back": {"UpperArm": (("z", -55.0), ("y", 35.0))},
    # Hands in front of her, clear of each other: with the forearms bent past 90 degrees the hands
    # met over her chest, and the test then counted her hands touching as a shoulder defect.
    "elbow-bent": {"UpperArm": (("z", -40.0), ("y", -20.0)), "LowerArm": (("y", -70.0),)},
}
_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

#: AN-A3. The leg poses her pelvic region is tested in (``wardrobe.anatomy.posecheck.PelvicRegion``),
#: arms in the sculpted pose. Same convention as ``TEST_POSES``; a part named without a side
#: applies to both legs mirrored, one named with a side to that leg only. Flexion is a negative
#: turn about x (her knee comes forward).
LEG_POSES: dict[str, dict[str, tuple[tuple[str, float], ...]]] = {
    "standing": {},
    "stride": {"leftUpperLeg": (("x", -30.0),), "rightUpperLeg": (("x", 20.0),)},
    "wide": {"UpperLeg": (("z", 30.0),)},
    "seated": {"UpperLeg": (("x", -85.0),), "LowerLeg": (("x", 85.0),)},
    "knee-up": {"leftUpperLeg": (("x", -90.0),), "leftLowerLeg": (("x", 90.0),)},
    "squat": {"UpperLeg": (("x", -110.0), ("z", 15.0)), "LowerLeg": (("x", 120.0),)},
}


def leg_pose(name: str, J: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """A named leg pose, with her arms where she was sculpted (so only her legs differ)."""
    out = dict(sculpted_pose(J))
    for part, turns in LEG_POSES[name].items():
        if part.startswith(("left", "right")):
            sides = [(part, 1.0)]
        else:
            sides = [("left" + part, 1.0), ("right" + part, -1.0)]
        for bone, mirror in sides:
            R = np.eye(3)
            for axis, degrees in turns:
                sign = mirror if axis in ("y", "z") else 1.0
                R = rotation(_AXES[axis], np.radians(sign * degrees)) @ R
            out[bone] = R
    return out


def named_pose(name: str, J: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """A named test pose as normalized-bone rotations for both sides (applied in the listed order)."""
    if name == "sculpted":
        return sculpted_pose(J)
    out = {}
    for part, turns in TEST_POSES[name].items():
        for side, mirror in (("left", 1.0), ("right", -1.0)):
            R = np.eye(3)
            for axis, degrees in turns:
                # Mirroring through her midline (x -> -x) flips turns about y and z, not about x.
                sign = mirror if axis in ("y", "z") else 1.0
                R = rotation(_AXES[axis], np.radians(sign * degrees)) @ R
            out[f"{side}{part}"] = R
    return out


__all__ = [
    "ARM_CHAIN",
    "BONES",
    "TEST_POSES",
    "VRM_BONES",
    "arm_angles",
    "base_weights",
    "bone_positions",
    "dense_weights",
    "LEG_POSES",
    "leg_pose",
    "named_pose",
    "pose_surface",
    "rotation",
    "sculpted_pose",
    "skin",
    "skinning_matrices",
    "t_pose",
    "unskin",
    "vrm_bone_of",
]
