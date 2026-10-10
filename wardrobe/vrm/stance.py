"""DC1. Heels are a stance, not a shape: her feet are turned down and she is lifted onto them.

A heeled boot cannot be built round a flat foot. The ball of her foot and her heel are on
the floor, so a stiletto under her heel either goes through the floor or leaves a wedge
of boot under the arch, and a platform under a flat foot is a box she is standing in. What
a shoe with a heel does to a person is turn the foot down at the ankle and lift her: the
ball stays on the sole, the heel rises onto the heel seat, the toes stay flat. That is the
stance, and every heeled boot here is built round it.

**Baked into her rest pose, the way VRoid Studio's own heels are.** Each foot is turned
about its ankle by ``pitch``, each toe joint back by the same angle (so the toes lie flat
on the sole), and the hips are raised by ``lift`` so the ball lands on the sole's top.
Every skinned mesh in the file — her body, her face, hair, earlier garments, decals — is
re-skinned into that pose with its own weights, and each skin's inverse bind matrices are
recomputed from the new joint matrices, so the file is bound at rest exactly as it was
before. The skeleton keeps its bones, names, hierarchy and weights; only three kinds of
rest transform change (hips, feet, toes). An animation that turns her foot turns it from
the new rest, and one that moves her hips is scaled by the new hip height, so she stays on
her heels when she moves.

**Recorded, so it can be changed.** The stance a look stands in is written on her hips
node (``extras.wardrobeForgeStance``) and in the look's tag. A later job that puts other
shoes on reads it and goes from that stance to the new one in a single bake (``apply``);
one that puts no shoes on leaves it alone, because her boots are still on. Flat shoes, or
none planned on an avatar standing flat, change nothing: every look made before DC1 is
byte-for-byte what it was.

Heights are absolute millimetres, as heels are sold, not graded by her height.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.visible import visible_vertices

#: Where the stance is written: the hips node's extras (the root's are rewritten each job).
STANCE_KEY = "wardrobeForgeStance"

#: Where her heel meets the heel seat, behind the ankle, as a share of ankle-to-ball length.
#: The heel's contact centre, not the back of the heel: that is rounded and off the floor.
HEEL_CONTACT_SHARE = 0.25

#: Never turned further than this, whatever the heel asks: past it the toes cannot stay flat.
MAX_PITCH_DEG = 55.0

_SIDES = ("left", "right")


@dataclass(frozen=True, slots=True)
class Stance:
    """How she stands: heel and sole heights asked for, and the pitch and lift that give them."""

    #: The underside of her heel above the floor.
    heel_m: float = 0.0
    #: The sole under the ball of her foot.
    platform_m: float = 0.0
    #: How far each foot is turned down about its ankle, degrees.
    pitch_deg: float = 0.0
    #: How far she is raised.
    lift_m: float = 0.0

    @property
    def flat(self) -> bool:
        return abs(self.pitch_deg) < 1e-6 and abs(self.lift_m) < 1e-6

    def to_dict(self) -> dict:
        return {
            "heelMm": round(self.heel_m * 1000.0, 2),
            "platformMm": round(self.platform_m * 1000.0, 2),
            "pitchDeg": round(self.pitch_deg, 4),
            "liftMm": round(self.lift_m * 1000.0, 4),
        }

    @classmethod
    def from_dict(cls, value: dict | None) -> Stance:
        if not isinstance(value, dict):
            return FLAT
        try:
            return cls(
                heel_m=float(value.get("heelMm", 0.0)) / 1000.0,
                platform_m=float(value.get("platformMm", 0.0)) / 1000.0,
                pitch_deg=float(value.get("pitchDeg", 0.0)),
                lift_m=float(value.get("liftMm", 0.0)) / 1000.0,
            )
        except (TypeError, ValueError):
            return FLAT


FLAT = Stance()


# ----------------------------------------------------------------------
# reading and solving
# ----------------------------------------------------------------------
def read(document: GltfDocument, info) -> Stance:
    """The stance this file stands in: what its hips node records, flat when nothing does."""
    hips = info.humanoid_bones.get("hips")
    if hips is None or hips >= len(document.nodes):
        return FLAT
    extras = document.nodes[hips].get("extras")
    return Stance.from_dict(extras.get(STANCE_KEY) if isinstance(extras, dict) else None)


def _rotation_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _about(pivot: np.ndarray, angle: float) -> np.ndarray:
    """4×4: turn ``angle`` about the world x axis through ``pivot``."""
    matrix = np.eye(4)
    rotation = _rotation_x(angle)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = pivot - rotation @ pivot
    return matrix


def _lift(height: float) -> np.ndarray:
    matrix = np.eye(4)
    matrix[1, 3] = height
    return matrix


def solve(
    ankle: np.ndarray,
    ball: np.ndarray,
    *,
    heel_m: float,
    platform_m: float,
    forward: float,
    floor_y: float = 0.0,
    lowest=None,
) -> Stance:
    """The pitch and lift that put her heel ``heel_m`` up and the ball on a ``platform_m`` sole.

    ``ankle`` and ``ball`` are the foot and toe joints standing flat; her heel meets the
    seat ``HEEL_CONTACT_SHARE`` of the foot behind the ankle. The lift puts the lowest
    point of her foot on the sole: ``lowest(pitch)`` is that point's height turned by
    ``pitch`` and not lifted, measured from her own vertices with her own weights. Without
    it, the ball's pad is taken to hang below its joint as it does flat, and stay there.
    """
    heel_m, platform_m = max(float(heel_m), 0.0), max(float(platform_m), 0.0)
    ankle, ball = np.asarray(ankle, dtype=np.float64), np.asarray(ball, dtype=np.float64)
    reach = abs(float(ball[2] - ankle[2]))
    heel = np.array([ankle[0], floor_y, ankle[2] - forward * HEEL_CONTACT_SHARE * reach, 1.0])
    ball_h = np.array([*ball, 1.0])

    def outcome(pitch: float) -> tuple[float, float]:
        turn = _about(ankle, forward * pitch)
        if lowest is not None:
            lift = platform_m + floor_y - float(lowest(pitch))
        else:
            lift = platform_m + float(ball_h[1] - (turn @ ball_h)[1])
        return lift, float((turn @ heel)[1]) + lift - floor_y

    if heel_m <= platform_m + 1e-4:
        return Stance(heel_m=heel_m, platform_m=platform_m, pitch_deg=0.0, lift_m=outcome(0.0)[0])
    lo, hi = 0.0, math.radians(MAX_PITCH_DEG)
    if outcome(hi)[1] < heel_m:
        lo = hi  # as high as a foot goes
    else:
        for _ in range(60):
            mid = (lo + hi) / 2.0
            lo, hi = (mid, hi) if outcome(mid)[1] < heel_m else (lo, mid)
    lift, _ = outcome(lo)
    return Stance(heel_m=heel_m, platform_m=platform_m, pitch_deg=math.degrees(lo), lift_m=lift)


# ----------------------------------------------------------------------
# the bake
# ----------------------------------------------------------------------
def _subtree(document: GltfDocument, root: int) -> set[int]:
    found, stack = set(), [root]
    while stack:
        index = stack.pop()
        if index in found or index >= len(document.nodes):
            continue
        found.add(index)
        stack.extend(document.nodes[index].get("children") or [])
    return found


def _stance_map(
    document: GltfDocument, info, world: list[np.ndarray], stance: Stance, forward: float
) -> dict[int, np.ndarray]:
    """World 4×4 that takes each node from standing flat (``world``) to ``stance``."""
    bones = info.humanoid_bones
    out: dict[int, np.ndarray] = {}
    hips = bones.get("hips")
    if hips is None or stance.flat:
        return out
    lift = _lift(stance.lift_m)
    for index in _subtree(document, hips):
        out[index] = lift
    angle = forward * math.radians(stance.pitch_deg)
    for side in _SIDES:
        foot = bones.get(f"{side}Foot")
        if foot is None:
            continue
        turn = _about(world[foot][:3, 3], angle)
        for index in _subtree(document, foot):
            out[index] = lift @ turn
        toes = bones.get(f"{side}Toes")
        if toes is not None:
            # Turned back about its own joint, standing flat, before the foot turns it down.
            flat_toes = _about(world[toes][:3, 3], -angle)
            for index in _subtree(document, toes):
                out[index] = lift @ turn @ flat_toes
    return out


def _flat_world(document: GltfDocument, info, current: Stance, forward: float) -> list[np.ndarray]:
    """Every node's world matrix as she stands flat, from a file standing in ``current``."""
    world = [m.copy() for m in document.world_matrices()]
    if current.flat:
        return world
    bones = info.humanoid_bones
    angle = forward * math.radians(current.pitch_deg)
    flat = [m.copy() for m in world]
    unlift = _lift(-current.lift_m)
    hips = bones.get("hips")
    for index in _subtree(document, hips) if hips is not None else ():
        flat[index] = unlift @ world[index]
    for side in _SIDES:
        foot = bones.get(f"{side}Foot")
        if foot is None:
            continue
        ankle = flat[foot][:3, 3].copy()  # the ankle only rises: its own turn leaves it where it is
        unturn = _about(ankle, -angle)
        for index in _subtree(document, foot):
            flat[index] = unturn @ unlift @ world[index]
        toes = bones.get(f"{side}Toes")
        if toes is not None:
            joint = flat[toes][:3, 3].copy()
            unflat = _about(joint, angle)
            for index in _subtree(document, toes):
                flat[index] = unflat @ unturn @ unlift @ world[index]
    return flat


def _quaternion(rotation: np.ndarray) -> list[float]:
    """(x, y, z, w) of a rotation matrix (Shepperd's method)."""
    m = rotation
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    norm = math.sqrt(sum(v * v for v in q)) or 1.0
    q = [v / norm for v in q]
    if q[3] < 0:
        q = [-v for v in q]
    return [float(v) for v in q]


def _write_local(node: dict, local: np.ndarray) -> None:
    if "matrix" in node:
        node["matrix"] = [float(v) for v in local.T.reshape(-1)]
        return
    scale = np.array(node.get("scale") or [1.0, 1.0, 1.0], dtype=np.float64)
    rotation = local[:3, :3] / np.where(np.abs(scale) > 1e-12, scale, 1.0)[None, :]
    node["translation"] = [float(v) for v in local[:3, 3]]
    quaternion = _quaternion(rotation)
    if np.allclose(quaternion, [0.0, 0.0, 0.0, 1.0], atol=1e-12):
        node.pop("rotation", None)
    else:
        node["rotation"] = quaternion


def _weights(document: GltfDocument, accessor: int) -> np.ndarray:
    values = document.read_accessor(accessor).astype(np.float64)
    info = document.gltf["accessors"][accessor]
    if info.get("normalized"):
        values /= {5121: 255.0, 5123: 65535.0}.get(int(info["componentType"]), 1.0)
    return values


def _blend(document: GltfDocument, attributes: dict, joint_deltas: np.ndarray) -> np.ndarray | None:
    """Per-vertex blended 4×4 of ``joint_deltas`` (indexed as the skin's joints), or None."""
    blended = None
    for set_index in range(4):
        joints_key, weights_key = f"JOINTS_{set_index}", f"WEIGHTS_{set_index}"
        if joints_key not in attributes or weights_key not in attributes:
            break
        joints = np.clip(
            document.read_accessor(attributes[joints_key]).astype(np.int64), 0, joint_deltas.shape[0] - 1
        )
        weights = _weights(document, attributes[weights_key])
        part = np.einsum("nk,nkij->nij", weights, joint_deltas[joints])
        blended = part if blended is None else blended + part
    if blended is None:
        return None
    totals = np.abs(blended[:, 3, 3])
    blended[totals < 1e-9] = np.eye(4)
    return blended / np.where(totals < 1e-9, 1.0, totals)[:, None, None]


def _store(document: GltfDocument, values: np.ndarray, *, bounds: bool = False) -> int:
    return document.add_accessor(values.astype(np.float32), target=34962, include_bounds=bounds)


def apply(document: GltfDocument, info, target: Stance, *, forward: float) -> Stance:
    """Bake ``target`` into ``document`` from whatever stance it stands in now; returns that one.

    Nothing is touched when the two are the same, so a flat avatar given flat shoes is
    byte-for-byte what it was.
    """
    current = read(document, info)
    if _same(current, target):
        return current
    flat = _flat_world(document, info, current, forward)
    before = _stance_map(document, info, flat, current, forward)
    after = _stance_map(document, info, flat, target, forward)
    old_world = document.world_matrices()
    count = len(document.nodes)
    delta = [np.eye(4)] * count
    for index in range(count):
        undo = np.linalg.inv(before[index]) if index in before else np.eye(4)
        delta[index] = after.get(index, np.eye(4)) @ undo
    new_world = [delta[i] @ old_world[i] for i in range(count)]

    # Joints: a node's local transform changes only where its delta differs from its parent's.
    parents = document.parent_map()
    for index in range(count):
        parent = parents.get(index)
        parent_delta = delta[parent] if parent is not None else np.eye(4)
        if np.allclose(delta[index], parent_delta, atol=1e-12):
            continue
        parent_world = new_world[parent] if parent is not None else np.eye(4)
        _write_local(document.nodes[index], np.linalg.inv(parent_world) @ new_world[index])
    document.invalidate_cache()

    _reskin(document, delta, before, after, old_world, new_world)
    hips = info.humanoid_bones.get("hips")
    if hips is not None:
        extras = document.nodes[hips].setdefault("extras", {})
        if target.flat:
            extras.pop(STANCE_KEY, None)
            if not extras:
                document.nodes[hips].pop("extras")
        else:
            extras[STANCE_KEY] = target.to_dict()
    return current


def _same(a: Stance, b: Stance) -> bool:
    return abs(a.pitch_deg - b.pitch_deg) < 1e-6 and abs(a.lift_m - b.lift_m) < 1e-7


def _reskin(
    document: GltfDocument,
    delta: list[np.ndarray],
    before: dict,
    after: dict,
    old_world: list[np.ndarray],
    new_world: list[np.ndarray],
) -> None:
    """Every skinned primitive into the new pose, and every skin rebound at it.

    A vertex is taken back to standing flat through *its own* blend of the stance it is in
    (``before``), then into the new one (``after``). Blending the joint-by-joint change
    instead is not the same thing wherever weights are shared — round her ankle — and a
    boot changed twice left her ankle 3 cm from where flat shoes would have put it.
    """
    skins = document.gltf.get("skins") or []
    done: dict[tuple[int, int], int] = {}
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        skin = node.get("skin")
        if skin is None or skin >= len(skins):
            continue
        joints = skins[skin].get("joints") or []
        joint_deltas = np.stack([delta[j] for j in joints] or [np.eye(4)])
        if np.allclose(joint_deltas, np.eye(4), atol=1e-12):
            continue
        joint_before = np.stack([before.get(j, np.eye(4)) for j in joints])
        joint_after = np.stack([after.get(j, np.eye(4)) for j in joints])
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            attributes = primitive.get("attributes", {})
            cache: list = []

            def blended(
                attributes=attributes, joint_before=joint_before, joint_after=joint_after, cache=cache
            ):
                if not cache:
                    undo = _blend(document, attributes, joint_before)
                    redo = _blend(document, attributes, joint_after)
                    cache.append(None if undo is None else redo @ np.linalg.inv(undo))
                return cache[0]

            # The base attributes, then each morph target's deltas (turned, never moved).
            slots = [(attributes, key, key == "POSITION") for key in ("POSITION", "NORMAL", "TANGENT")]
            slots += [
                (target, key, False)
                for target in primitive.get("targets") or []
                for key in ("POSITION", "NORMAL", "TANGENT")
            ]
            for holder, key, moves in slots:
                if key not in holder:
                    continue
                source = holder[key]
                if (source, skin) in done:
                    holder[key] = done[(source, skin)]
                    continue
                matrices = blended()
                if matrices is None:
                    break
                values = document.read_accessor(source).astype(np.float64)
                if moves:
                    homogeneous = np.hstack([values[:, :3], np.ones((values.shape[0], 1))])
                    out = np.einsum("nij,nj->ni", matrices, homogeneous)[:, :3]
                else:
                    out = np.einsum("nij,nj->ni", matrices[:, :3, :3], values[:, :3])
                    if holder is attributes:  # a base normal or tangent stays unit length
                        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
                    if values.shape[1] == 4:
                        out = np.hstack([out, values[:, 3:4]])
                stored = _store(document, out, bounds=key == "POSITION")
                done[(source, skin)] = stored
                holder[key] = stored
    for skin in skins:
        joints = skin.get("joints") or []
        source = skin.get("inverseBindMatrices")
        if source is None or not joints:
            continue
        if all(np.allclose(delta[j], np.eye(4), atol=1e-12) for j in joints):
            continue
        inverse = document.read_accessor(source).astype(np.float64).reshape(-1, 4, 4).transpose(0, 2, 1)
        rebound = np.stack(
            [np.linalg.inv(new_world[j]) @ old_world[j] @ inverse[k] for k, j in enumerate(joints)]
        )
        skin["inverseBindMatrices"] = document.add_accessor(
            rebound.transpose(0, 2, 1).reshape(-1, 16).astype(np.float32)
        )


def flat_feet(document: GltfDocument, info, forward: float) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """(ankle, ball) joint positions per side as she stands flat, whatever stance the file is in."""
    world = _flat_world(document, info, read(document, info), forward)
    out = {}
    for side in _SIDES:
        foot, toes = info.humanoid_bones.get(f"{side}Foot"), info.humanoid_bones.get(f"{side}Toes")
        if foot is None or toes is None:
            continue
        out[side] = (world[foot][:3, 3].copy(), world[toes][:3, 3].copy())
    return out


#: Her foot, for the stance: vertices moved mostly by a foot or toe bone, this near the ankle.
#: Further out is not foot: AvatarSample A's Bottoms hides vertices 26 cm behind her heel.
FOOT_REACH_M = 0.25


def _foot_samples(document: GltfDocument, info) -> list[tuple]:
    """(positions, joints, weights, skin joint nodes) of every drawn vertex of her feet, as she stands."""
    bones = info.humanoid_bones
    feet = [bones[f"{side}Foot"] for side in _SIDES if f"{side}Foot" in bones]
    if not feet:
        return []
    foot_nodes = set().union(*(_subtree(document, foot) for foot in feet))
    world = document.world_matrices()
    ankles = np.stack([world[foot][:3, 3] for foot in feet])
    skins = document.gltf.get("skins") or []
    samples = []
    textures: dict = {}
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        if node.get("skin") is None or node["skin"] >= len(skins):
            continue
        joint_nodes = list(skins[node["skin"]].get("joints") or [])
        if not joint_nodes or not foot_nodes & set(joint_nodes):
            continue
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
                continue
            positions = document.read_accessor(attributes["POSITION"]).astype(np.float64)[:, :3]
            drawn = (
                np.unique(document.read_accessor(primitive["indices"]).reshape(-1).astype(np.int64))
                if primitive.get("indices") is not None
                else np.arange(positions.shape[0])
            )
            joints = np.clip(
                document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)[drawn],
                0,
                len(joint_nodes) - 1,
            )
            weights = _weights(document, attributes["WEIGHTS_0"])[drawn]
            dominant = np.array(joint_nodes)[joints[np.arange(drawn.size), weights.argmax(axis=1)]]
            near = np.min(np.linalg.norm(positions[drawn][:, None, :] - ankles[None], axis=2), axis=1)
            keep = np.isin(dominant, list(foot_nodes)) & (near < FOOT_REACH_M)
            shown = visible_vertices(document, primitive, textures)
            if shown is not None:  # what her textures cut away is not foot (wardrobe.vrm.visible)
                keep &= shown[drawn]
            if keep.any():
                samples.append((positions[drawn][keep], joints[keep], weights[keep], joint_nodes))
    return samples


def stance_for(
    document: GltfDocument, info, *, heel_m: float, platform_m: float, forward: float
) -> Stance | None:
    """The stance a pair of shoes asks for on this avatar, or None when it has no feet to stand on."""
    if heel_m <= 0.0 and platform_m <= 0.0:
        return FLAT
    feet = flat_feet(document, info, forward)
    if not feet:
        return None
    ankle = np.mean([a for a, _ in feet.values()], axis=0)
    ball = np.mean([b for _, b in feet.values()], axis=0)
    ankle[0] = ball[0] = 0.0
    current = read(document, info)
    flat = _flat_world(document, info, current, forward)
    before = _stance_map(document, info, flat, current, forward)
    samples = _foot_samples(document, info)

    def lowest(pitch: float) -> float:
        after = _stance_map(document, info, flat, Stance(pitch_deg=math.degrees(pitch), lift_m=1e-9), forward)
        low = math.inf
        for positions, joints, weights, joint_nodes in samples:
            deltas = np.stack(
                [after.get(j, np.eye(4)) @ np.linalg.inv(before.get(j, np.eye(4))) for j in joint_nodes]
            )
            blended = np.einsum("nk,nkij->nij", weights, deltas[joints])
            total = np.where(np.abs(blended[:, 3, 3]) < 1e-9, 1.0, blended[:, 3, 3])
            y = (np.einsum("nj,nj->n", blended[:, 1, :3], positions) + blended[:, 1, 3]) / total
            low = min(low, float(y.min()))
        return low

    return solve(
        ankle, ball, heel_m=heel_m, platform_m=platform_m, forward=forward, lowest=lowest if samples else None
    )


__all__ = [
    "FLAT",
    "HEEL_CONTACT_SHARE",
    "MAX_PITCH_DEG",
    "STANCE_KEY",
    "Stance",
    "apply",
    "flat_feet",
    "read",
    "solve",
    "stance_for",
]
