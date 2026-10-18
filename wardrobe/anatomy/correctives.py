"""SA3. Pose-space correctives: her armpits close on themselves without passing through.

**Why skinning is not enough here.** With MakeHuman's weights and the solved bind (``rig``) her
shoulders hold their shape in every test pose, but an arm lowered past the angle she was sculpted
at (47 degrees below level) sweeps its inner surface into the side of her chest. Real tissue is
pressed flat there; linear blend skinning has no notion of contact and lets the two surfaces
pass. Within 17 cm of the shoulders the median body had 250 crossing edges in the Studio's
relaxed pose and 532 with her arms at her sides, almost all arm into trunk.

**What a corrective is.** For each key pose (``KEYS``: how far the arm points below level) the
contact is resolved once, offline, and stored as a morph target: a displacement in the bind pose
that the viewer's own skinning carries exactly onto the resolved surface at that pose. A viewer
drives each target from the arm's angle (``KEYS`` gives the curve; ``apps/studio/js/viewer.js``
reads it from the file's extras), so between keys the correction blends. A viewer that does not
drive them shows plain skinning, which is clean everywhere except where the armpit closes.

**How the contact is resolved.** On MakeHuman's control mesh, not the subdivided surface: the body
*is* that control mesh subdivided twice, so a correction made there and subdivided is as smooth as
she is, and the solve is small. A control vertex has passed into her when the winding number of the
whole closed body about it is above 1 (a point on her surface reads one half; one that has entered
another part of her, one and a half). Only vertices with a facing vertex of the other part (arm
against trunk) within ``NEAR_M`` are tested: deep creases also read above one half, and the armpit
fold is one. Each such vertex steps ``STEP_M`` into itself along its own inward normal — the arm and
the trunk each give way, as tissue does — and the step is spread over its neighbours so the contact
patch has no rim. A smooth surface over a clean control mesh can still dip through between control
points, so the subdivided surface is then checked for crossings, and the control vertices that
shape each crossing are pressed further; until there are none, or ``CAP_M`` has been spent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.anatomy import reference as R
from wardrobe.anatomy import rig
from wardrobe.anatomy import template as TM
from wardrobe.anatomy.topology import self_intersections

#: The key poses: how far each arm points below level, and how far it is swung forward (+) or back
#: (-), degrees, measured in her chest's frame; and the curves a viewer drives each target by, its
#: weight the product of one over the down angle and one over the swing. Contact begins below the
#: sculpted 47 degrees, and earlier with the arm swung back (the rear of the armpit closes first);
#: ``sculpted`` in a curve is replaced by her own sculpted angle; "relaxed" is the Studio's pose
#: (1.18 rad from the T). Past its last key a curve holds that key's weight.
#:
#: There is no key with her arms at her sides. At 82 degrees pressing arm and chest in until they
#: meet folded the arm through itself (1 492 crossings after 57 mm of travel, from 532 under plain
#: skinning). A real shoulder does not rotate about a fixed point there: the girdle
#: drops and draws back as the arm comes down. Nothing here models that, so the relaxed corrective
#: fades out by 82 degrees (held on, it made two sizes worse there: full 572 -> 650 crossings) and
#: the contact with her arms at her sides is left to plain skinning, and reported
#: (docs/ANATOMY_REFERENCE.md, "Shoulders").
KEYS = (
    {
        "name": "relaxed",
        "down": 67.6,
        "swing": 0.0,
        "keys": [["sculpted", 0.0], [67.6, 1.0], [82.0, 0.0]],
        "swingKeys": [[-35.0, 0.0], [0.0, 1.0], [35.0, 0.0]],
    },
    {
        "name": "back",
        "down": 55.0,
        "swing": -35.0,
        "keys": [[40.0, 0.0], [55.0, 1.0]],
        "swingKeys": [[-35.0, 1.0], [0.0, 0.0]],
    },
    {
        "name": "forward",
        "down": 66.0,
        "swing": 35.0,
        "keys": [[52.0, 0.0], [66.0, 1.0]],
        "swingKeys": [[0.0, 0.0], [35.0, 1.0], [60.0, 0.0]],
    },
    {
        # Raised in front of her the front of the armpit closes instead: on the tall size the arm
        # passed into her chest there (112 crossings within 17 cm of the shoulders).
        "name": "raisedForward",
        "down": 10.0,
        "swing": 85.0,
        "keys": [[-20.0, 0.0], [10.0, 1.0], [40.0, 0.0]],
        "swingKeys": [[50.0, 0.0], [85.0, 1.0]],
    },
)
STEP_M = 0.002
CAP_M = 0.035
NEAR_M = 0.04
#: Control vertices within this of a shoulder joint may move; crossings are sought this far out too
#: (with her arms at her sides the arm meets her chest well below the 17 cm the shoulder metric uses).
REGION_M = 0.30
ROUNDS = 16
#: Control-vertex presses between two checks of the subdivided surface for crossings.
PRESSES_PER_CHECK = 3
SIDES = (("left", "l", 1.0), ("right", "r", -1.0))


@dataclass
class Corrective:
    """One morph target: a bind-pose displacement for one side, driven by that side's upper arm."""

    name: str
    bone: str
    axis: tuple[float, float, float]
    keys: list[list[float]]  # [[degrees below level, weight], ...], linear between, held at the ends
    swing_keys: list[list[float]]  # [[degrees forward (+) / back (-), weight], ...], the same way
    delta: np.ndarray  # (vertices, 3) float32, zero off her side

    def spec(self) -> dict:
        return {
            "target": self.name,
            "bone": self.bone,
            "frame": "upperChest",
            "axis": list(self.axis),
            "keys": self.keys,
            "swingKeys": self.swing_keys,
        }


def key_pose(down_degrees: float, swing_degrees: float = 0.0) -> dict[str, np.ndarray]:
    """Both upper arms lowered by ``down_degrees`` in her frontal plane, then swung about the vertical."""
    return {
        f"{side}UpperArm": rig.rotation((0, 1, 0), np.radians(-sign * swing_degrees))
        @ rig.rotation((0, 0, 1), np.radians(-sign * down_degrees))
        for side, _, sign in SIDES
    }


def _normals(X: np.ndarray, F: np.ndarray) -> np.ndarray:
    n = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
    N = np.zeros_like(X)
    for k in range(3):
        np.add.at(N, F[:, k], n)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-15)


def winding(P: np.ndarray, X: np.ndarray, F: np.ndarray, chunk: int = 64) -> np.ndarray:
    """Generalized winding number of the closed triangle surface (X, F) about each point (solid angles)."""
    out = np.zeros(len(P))
    A, B, C = X[F[:, 0]], X[F[:, 1]], X[F[:, 2]]
    for s in range(0, len(P), chunk):
        p = P[s : s + chunk, None, :]
        a, b, c = A[None] - p, B[None] - p, C[None] - p
        la, lb, lc = (np.linalg.norm(v, axis=2) for v in (a, b, c))
        det = np.einsum("pij,pij->pi", a, np.cross(b, c))
        dot = (
            la * lb * lc
            + np.einsum("pij,pij->pi", a, b) * lc
            + np.einsum("pij,pij->pi", b, c) * la
            + np.einsum("pij,pij->pi", c, a) * lb
        )
        out[s : s + chunk] = (2 * np.arctan2(det, dot)).sum(axis=1) / (4 * np.pi)
    return out


def _subdivide(D: np.ndarray, levels: int) -> np.ndarray:
    for step in TM.subdivision(levels) if levels else ():
        D = step.apply(D)
    return D


def _cage_influence(fine: np.ndarray, levels: int) -> np.ndarray:
    """How much each control vertex shapes the marked fine vertices (the subdivision transposed)."""
    w = fine.astype(np.float64)
    for step in reversed(TM.subdivision(levels)):
        coarse = np.zeros(int(step.cols.max()) + 1)
        np.add.at(coarse, step.cols, w[step.rows] * step.vals)
        w = coarse
    return w


def _arm_share(count: int) -> np.ndarray:
    W = rig.dense_weights(count)
    return W[:, [rig.VRM_BONES.index(b) for side, _, _ in SIDES for b in rig.ARM_CHAIN[side]]].sum(axis=1)


def resolve_contact(
    cage_rest: np.ndarray,
    cage_bound: np.ndarray,
    fine_rest: np.ndarray,
    fine_bound: np.ndarray,
    fine_tris: np.ndarray,
    J: dict[str, np.ndarray],
    bind: dict[str, np.ndarray],
    pose: dict[str, np.ndarray],
    levels: int,
) -> tuple[np.ndarray, dict]:
    """The fine surface in ``pose`` with its armpits resolved, and what it took.

    ``*_rest`` are the sculpted surfaces (for regions), ``*_bound`` the T-posed ones the skin binds.
    """
    quads = TM.template().faces
    cage_tris = TM.triangles(quads)
    edges = np.unique(
        np.sort(
            np.concatenate([quads[:, [0, 1]], quads[:, [1, 2]], quads[:, [2, 3]], quads[:, [3, 0]]]), axis=1
        ),
        axis=0,
    )
    degree = np.bincount(edges.ravel(), minlength=len(cage_rest)).astype(float)
    region = np.zeros(len(cage_rest), bool)
    fine_region = np.zeros(len(fine_rest), bool)
    for _, s, _ in SIDES:
        joint = J[f"joint-{s}-shoulder"]
        same = np.sign(cage_rest[:, 0]) == np.sign(joint[0])
        region |= (np.linalg.norm(cage_rest - joint, axis=1) < REGION_M) & same
        fine_region |= (np.linalg.norm(fine_rest - joint, axis=1) < REGION_M) & (
            np.sign(fine_rest[:, 0]) == np.sign(joint[0])
        )
    idx = np.where(region)[0]
    arm = _arm_share(len(cage_rest))
    arm_side, trunk_side = idx[arm[idx] >= 0.5], idx[arm[idx] < 0.5]
    tris = fine_tris[fine_region[fine_tris].all(axis=1)]
    tri_edges = np.unique(
        np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1), axis=0
    )

    X0 = rig.pose_surface(cage_bound, bind, pose)
    fine0 = rig.pose_surface(fine_bound, bind, pose)
    X = X0.copy()

    def spread(D: np.ndarray, fixed: np.ndarray, passes: int = 3) -> np.ndarray:
        for _ in range(passes):
            acc = np.zeros_like(D)
            np.add.at(acc, edges[:, 0], D[edges[:, 1]])
            np.add.at(acc, edges[:, 1], D[edges[:, 0]])
            D = np.where(
                fixed[:, None], D, np.where(region[:, None], 0.5 * acc / np.maximum(degree, 1)[:, None], 0.0)
            )
        return D

    def press(chosen: np.ndarray, N: np.ndarray) -> np.ndarray:
        chosen = chosen[np.linalg.norm(X[chosen] - X0[chosen], axis=1) < CAP_M]
        D = np.zeros_like(X)
        D[chosen] = -STEP_M * N[chosen]  # each side gives way into itself
        fixed = np.zeros(len(X), bool)
        fixed[chosen] = True
        return spread(D, fixed), chosen.size

    # The best state seen, starting from none at all: a key the solve cannot clear must never ship
    # a correction worse than plain skinning. On the full size swung back, pressing on folded the
    # arm through itself (640 crossings after 41 mm, from fewer under plain skinning).
    plain = int(self_intersections(fine0, tris, tri_edges)[0].size)
    best = (plain, X0.copy())
    steps = 0
    crossings = plain
    for _ in range(ROUNDS if plain else 0):
        for _ in range(40):  # the control mesh: nothing of one part inside another
            N = _normals(X, cage_tris)
            near = np.zeros(len(X), bool)
            for P, Q in ((arm_side, trunk_side), (trunk_side, arm_side)):
                d = np.linalg.norm(X[P][:, None, :] - X[Q][None, :, :], axis=2)
                near[P[((d < NEAR_M) & ((N[P] @ N[Q].T) < 0)).any(axis=1)]] = True
            candidates = np.where(near)[0]
            inside = candidates[winding(X[candidates], X, cage_tris) > 1.0] if candidates.size else candidates
            D, moved = press(inside, N)
            if not moved:
                break
            X = X + D
            steps += 1
        fine = fine0 + _subdivide(X - X0, levels)
        e, _ = self_intersections(fine, tris, tri_edges)
        crossings = int(e.size)
        if crossings < best[0]:
            best = (crossings, X.copy())
        if not crossings:
            break
        # The fine surface still dips through: press the control vertices that shape the crossings.
        marked = np.zeros(len(fine))
        marked[np.unique(tri_edges[e])] = 1.0
        influence = _cage_influence(marked, levels)
        chosen = np.where((influence > 0.05) & region)[0]
        moved = 0
        for _ in range(PRESSES_PER_CHECK):  # the fine check is the costly part: press a few steps per check
            D, moved = press(chosen, _normals(X, cage_tris))
            if not moved:
                break
            X = X + D
            steps += 1
        if not moved:
            break
    crossings, X = best
    fine = fine0 + _subdivide(X - X0, levels)
    report = {
        "steps": steps,
        "crossingsSkinning": plain,
        "crossings": crossings,
        "maxControlDisplacementMm": round(float(np.linalg.norm(X - X0, axis=1).max() * 1000), 2),
    }
    return fine, report


def build(size_id: str, names: tuple[str, ...] | None = None) -> tuple[list[Corrective], dict]:
    """A size's correctives, in the order the VRM lists them, and how each key resolved.

    ``names`` builds only those keys (a test that needs one key need not solve them all).
    """
    keys = [k for k in KEYS if names is None or k["name"] in names]
    modifiers = R.reference_bodies()["bodies"][size_id]["modifiers"]
    cage_rest, _, J = R.build(modifiers, 0)
    fine_rest, fine_tris, _ = R.build(modifiers, R.LEVELS)
    cage_bound, TJ = rig.t_pose(cage_rest, J)
    fine_bound, _ = rig.t_pose(fine_rest, J)
    bind = rig.bone_positions(TJ)
    sculpted = np.degrees(rig.arm_angles(J)["left"])
    out, reports = [], {}
    deltas = {}
    for key in keys:
        name, pose = key["name"], key_pose(key["down"], key["swing"])
        target, reports[name] = resolve_contact(
            cage_rest, cage_bound, fine_rest, fine_bound, fine_tris.reshape(-1, 3), J, bind, pose, R.LEVELS
        )
        # Back into the bind pose through the skinning at this pose: driven at the key, the viewer
        # lands exactly on the resolved surface.
        deltas[name] = rig.unskin(target, bind, pose) - fine_bound
    for key in keys:
        curve = [[round(float(sculpted), 2) if x == "sculpted" else x, y] for x, y in key["keys"]]
        for side, _, sign in SIDES:
            delta = np.where((np.sign(fine_rest[:, 0]) == sign)[:, None], deltas[key["name"]], 0.0)
            delta[np.linalg.norm(delta, axis=1) < 1e-7] = 0.0
            out.append(
                Corrective(
                    name=f"corrective.{side}Arm.{key['name']}",
                    bone=f"{side}UpperArm",
                    axis=(sign, 0.0, 0.0),
                    keys=curve,
                    swing_keys=[list(k) for k in key["swingKeys"]],
                    delta=delta.astype(np.float32),
                )
            )
    return out, reports


def arm_angles(pose: dict[str, np.ndarray], bone: str, axis) -> tuple[float, float]:
    """(degrees below level, degrees swung forward) of a bone's arm in a pose, in her chest's frame.

    The test poses turn the upper arms only, so the chest's frame is the world's here; the viewer
    reads the same two angles relative to her upper chest, so turning her whole figure changes
    neither.
    """
    d = pose.get(bone, np.eye(3)) @ np.asarray(axis, dtype=np.float64)
    down = float(np.degrees(np.arcsin(np.clip(-d[1], -1.0, 1.0))))
    swing = float(np.degrees(np.arctan2(d[2], axis[0] * d[0])))
    return down, swing


def weight(degrees: float, keys: list[list[float]]) -> float:
    """One curve of the driver: linear between keys, held at the ends (``correctiveWeight`` in the viewer)."""
    xs, ys = [k[0] for k in keys], [k[1] for k in keys]
    return float(np.interp(degrees, xs, ys))


def driven_weight(corrective: Corrective, pose: dict[str, np.ndarray]) -> float:
    down, swing = arm_angles(pose, corrective.bone, corrective.axis)
    return weight(down, corrective.keys) * weight(swing, corrective.swing_keys)


def driven_morph(correctives: list[Corrective], pose: dict[str, np.ndarray]) -> np.ndarray:
    """The summed morph a driving viewer applies in ``pose``."""
    out = np.zeros_like(correctives[0].delta, dtype=np.float64)
    for c in correctives:
        out += driven_weight(c, pose) * c.delta
    return out


__all__ = [
    "CAP_M",
    "KEYS",
    "Corrective",
    "build",
    "arm_angles",
    "driven_morph",
    "driven_weight",
    "key_pose",
    "weight",
    "winding",
]
