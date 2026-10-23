"""Garment-to-body contact in HomePilot's poses, measured on a fitted VRM: numbers, no pictures.

    python tools/inspect/pose_contact.py LOOK.vrm --poses POSES.json [--garment "Wine Tailored Briefs"]

The fit report's pose check (geometry_checks.pose_stress_test) deforms the garment alone and
asks whether it stays finite and how far an edge stretches: a brief can pass it while sunk
two centimetres into her thigh. This poses the whole file — her skin and every garment, each
by its own joints and weights — with the bone rotations HomePilot's Pose Studio applies, and
measures each garment against her posed skin.

POSES.json is ``[{"name", "bones": {humanoidBone: [x, y, z, w]}}]``, the normalized-bone
quaternions HomePilot's VRPoseSystem holds (export them with tools/inspect/export-poses.mjs or
by hand). The rest pose is always measured first, as the baseline.

Per garment and pose, in millimetres where it is a length:

* ``minClearanceMm``  smallest signed distance from a garment vertex to her skin (negative is
  inside her);
* ``maxPenetrationMm`` the deepest a garment vertex is inside her (0 when none is);
* ``penetratingPct``  the share of garment vertices more than 1 mm inside her;
* ``maxEdgeStretch``  the most any garment edge is stretched against its rest length;
* ``stretchedPct``    the share of edges stretched past 1.5x.

Inside is decided against her nearest skin vertex's normal, posed with her: exact enough to
rank poses and garments, not a watertight solid test. Her texture is not read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.engines.native import _posed  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402
from wardrobe.vrm.weight_transfer import _nearest  # noqa: E402

PENETRATING_M = 0.001
STRETCHED = 1.5


def _quat_matrix(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def pose_deltas(document: GltfDocument, humanoid: dict[str, int], bones: dict,
                vrm0: bool) -> dict[int, np.ndarray]:
    """node -> world delta (posed world @ inverse rest world) for HomePilot's normalized rotations.

    A normalized rotation is expressed in a frame aligned with the world at rest; for a VRM 0.x
    model, which faces -z, three-vrm turns that frame half round, which negates x and z.
    """
    rest = document.world_matrices()
    rotation = {}
    for name, q in bones.items():
        node = humanoid.get(name)
        if node is None:
            continue
        x, y, z, w = q
        rotation[node] = _quat_matrix((-x, y, -z, w) if vrm0 else (x, y, z, w))
    parents = document.parent_map()
    posed: dict[int, np.ndarray] = {}

    def world(index: int) -> np.ndarray:
        if index in posed:
            return posed[index]
        parent = parents.get(index)
        parent_rest = rest[parent] if parent is not None else np.eye(4)
        parent_posed = world(parent) if parent is not None else np.eye(4)
        local = np.linalg.inv(parent_rest) @ rest[index]
        if index in rotation:
            # A world-aligned turn about the bone's own head, in the parent's posed frame.
            spin = np.eye(4)
            spin[:3, :3] = rest[index][:3, :3] @ rotation[index] @ np.linalg.inv(rest[index][:3, :3])
            head = np.eye(4)
            head[:3, 3] = rest[index][:3, 3]
            local = np.linalg.inv(parent_rest) @ head @ spin @ np.linalg.inv(head) @ rest[index]
        posed[index] = parent_posed @ local
        return posed[index]

    return {index: world(index) @ np.linalg.inv(rest[index]) for index in range(len(document.nodes))}


def _humanoid_names(document: GltfDocument, humanoid: dict[str, int]) -> dict[int, str]:
    """node -> the humanoid bone it is or hangs from (VRoid's helper bones fold onto theirs)."""
    by_node = {node: name for name, node in humanoid.items()}
    parents = document.parent_map()
    out = {}
    for index in range(len(document.nodes)):
        cursor = index
        while cursor is not None and cursor not in by_node:
            cursor = parents.get(cursor)
        out[index] = by_node.get(cursor, "other")
    return out


def _dominant_bone(document, node, attributes, names_of) -> np.ndarray:
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    joint_nodes = document.gltf["skins"][node["skin"]]["joints"]
    top = joints[np.arange(joints.shape[0]), np.argmax(weights, axis=1)]
    return np.array([names_of.get(joint_nodes[j], "other") for j in top])


def _count(values: np.ndarray) -> dict:
    names, counts = np.unique(values, return_counts=True)
    return {str(n): int(c) for n, c in sorted(zip(names, counts, strict=True), key=lambda t: -t[1])}


def _primitives(document: GltfDocument):
    """(material name, node, attributes, rest points, triangles) for every skinned primitive."""
    materials = document.gltf.get("materials") or []
    for node in document.nodes:
        if node.get("mesh") is None or node.get("skin") is None:
            continue
        for primitive in document.meshes[node["mesh"]]["primitives"]:
            attributes = primitive["attributes"]
            index = primitive.get("material")
            name = materials[index].get("name", "") if index is not None and index < len(materials) else ""
            points = document.read_accessor(attributes["POSITION"]).astype(np.float64)
            tris = (document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
                    if "indices" in primitive else np.arange(points.shape[0]).reshape(-1, 3))
            yield name, node, attributes, points, tris


def measure(path: Path, poses: list[dict], garments: list[str]) -> dict:
    document = GltfDocument.from_bytes(path.read_bytes())
    info = inspect_document(document)
    vrm0 = info.spec is VrmSpec.VRM0
    prims = list(_primitives(document))
    # Her skin: VRoid names it by role (_SKIN); a calibration body's one material is "Body".
    skin = [p for p in prims if "_SKIN" in p[0] or p[0] == "Body"]
    body_roles = ("_SKIN", "_FACE", "_EYE", "_HAIR", "_CLOTH")
    chosen = [p for p in prims if any(p[0].startswith(g) for g in garments)] if garments else [
        p for p in prims if "[Forge_" in p[0] or (p[0] != "Body" and not any(t in p[0] for t in body_roles))]
    report: dict = {"file": path.name, "spec": "VRM0" if vrm0 else "VRM1", "garments": {}}
    names_of = _humanoid_names(document, info.humanoid_bones)
    for pose in [{"name": "rest", "bones": {}}, *poses]:
        deltas = pose_deltas(document, info.humanoid_bones, pose["bones"], vrm0)
        body_points, body_normals = [], []
        for _name, node, attributes, points, _tris in skin:
            posed = _posed(document, node, attributes, points, deltas)
            normals = (document.read_accessor(attributes["NORMAL"]).astype(np.float64)
                       if "NORMAL" in attributes else None)
            if normals is not None:
                moved = _posed(document, node, attributes, points + normals * 0.01, deltas) - posed
                normals = moved / np.maximum(np.linalg.norm(moved, axis=1, keepdims=True), 1e-9)
                body_points.append(posed)
                body_normals.append(normals)
        if not body_points:
            raise SystemExit("no skin with normals to measure against")
        cloud, cloud_normals = np.vstack(body_points), np.vstack(body_normals)
        if "cloud_bone" not in locals():
            cloud_bone = np.concatenate([_dominant_bone(document, node, attributes, names_of)
                                         for _n, node, attributes, _p, _t in skin
                                         if "NORMAL" in attributes])
        for name, node, attributes, points, tris in chosen:
            posed = _posed(document, node, attributes, points, deltas)
            index, _ = _nearest(posed, cloud, 1)
            nearest = index[:, 0]
            signed = np.einsum("ij,ij->i", posed - cloud[nearest], cloud_normals[nearest])
            rest_edges = np.linalg.norm(points[tris[:, 0]] - points[tris[:, 1]], axis=1)
            posed_edges = np.linalg.norm(posed[tris[:, 0]] - posed[tris[:, 1]], axis=1)
            usable = rest_edges > 1e-6
            ratio = posed_edges[usable] / rest_edges[usable]
            report["garments"].setdefault(name, {})[pose["name"]] = {
                "minClearanceMm": round(float(signed.min()) * 1000, 1),
                "maxPenetrationMm": round(float(max(0.0, -signed.min())) * 1000, 1),
                "penetratingPct": round(float((signed < -PENETRATING_M).mean()) * 100, 2),
                "maxEdgeStretch": round(float(ratio.max()), 2) if ratio.size else 1.0,
                "stretchedPct": round(float((ratio > STRETCHED).mean()) * 100, 2) if ratio.size else 0.0,
                # Where the inside points are: the bone carrying her nearest skin.
                "insideBy": _count(cloud_bone[nearest[signed < -PENETRATING_M]]),
            }
    return report


def _ramp(t: np.ndarray, stops: list[tuple[float, tuple[float, float, float]]]) -> np.ndarray:
    xs = [x for x, _ in stops]
    return np.stack([np.interp(t, xs, [c[k] for _, c in stops]) for k in range(3)], axis=1)


#: Clearance in mm -> colour: clear blue, contact green, inside yellow to red (15 mm).
CLEARANCE_STOPS = [(-15.0, (0.80, 0.05, 0.05)), (-5.0, (0.95, 0.55, 0.05)), (-1.0, (0.95, 0.90, 0.10)),
                   (0.0, (0.15, 0.75, 0.25)), (2.0, (0.15, 0.75, 0.25)), (8.0, (0.20, 0.45, 0.90))]
#: Stretch ratio -> colour: at rest white, 1.5x yellow, 2.5x and more red.
STRETCH_STOPS = [(1.0, (0.92, 0.92, 0.92)), (1.5, (0.95, 0.85, 0.10)), (2.5, (0.80, 0.05, 0.05))]


def coloured(path: Path, pose: dict, garments: list[str], mode: str, out: Path) -> dict:
    """A copy of ``path`` whose ``garments`` carry COLOR_0: their clearance or stretch in ``pose``.

    For the engineering views only (the gallery page's present.vertexColors); the source file
    is not written. Returns the same per-garment measurements ``measure`` reports for the pose.
    """
    document = GltfDocument.from_bytes(path.read_bytes())
    info = inspect_document(document)
    vrm0 = info.spec is VrmSpec.VRM0
    deltas = pose_deltas(document, info.humanoid_bones, pose["bones"], vrm0)
    prims = list(_primitives(document))
    cloud, normals = [], []
    for name, node, attributes, points, _t in prims:
        if ("_SKIN" in name or name == "Body") and "NORMAL" in attributes:
            posed = _posed(document, node, attributes, points, deltas)
            n = document.read_accessor(attributes["NORMAL"]).astype(np.float64)
            moved = _posed(document, node, attributes, points + n * 0.01, deltas) - posed
            cloud.append(posed)
            normals.append(moved / np.maximum(np.linalg.norm(moved, axis=1, keepdims=True), 1e-9))
    cloud, normals = np.vstack(cloud), np.vstack(normals)
    for mesh in document.meshes:
        for primitive in mesh["primitives"]:
            materials = document.gltf.get("materials") or []
            index = primitive.get("material")
            name = materials[index].get("name", "") if index is not None else ""
            if not any(name.startswith(g) for g in garments):
                continue
            node = next(n for n in document.nodes if n.get("mesh") is not None
                        and document.meshes[n["mesh"]] is mesh)
            attributes = primitive["attributes"]
            points = document.read_accessor(attributes["POSITION"]).astype(np.float64)
            posed = _posed(document, node, attributes, points, deltas)
            if mode == "clearance":
                index, _ = _nearest(posed, cloud, 1)
                signed = np.einsum("ij,ij->i", posed - cloud[index[:, 0]], normals[index[:, 0]]) * 1000
                colours = _ramp(signed, CLEARANCE_STOPS)
            else:
                tris = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
                ratio = np.ones(points.shape[0])
                for a, b in ((0, 1), (1, 2), (2, 0)):
                    rest = np.linalg.norm(points[tris[:, a]] - points[tris[:, b]], axis=1)
                    now = np.linalg.norm(posed[tris[:, a]] - posed[tris[:, b]], axis=1)
                    r = np.where(rest > 1e-6, now / np.maximum(rest, 1e-9), 1.0)
                    np.maximum.at(ratio, tris[:, a], r)
                    np.maximum.at(ratio, tris[:, b], r)
                colours = _ramp(ratio, STRETCH_STOPS)
            rgba = np.hstack([colours, np.ones((colours.shape[0], 1))]).astype(np.float32)
            attributes["COLOR_0"] = document.add_accessor(rgba)
    out.write_bytes(document.to_bytes())
    return measure(path, [pose], garments)["garments"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vrm", type=Path)
    parser.add_argument("--poses", type=Path, required=True)
    parser.add_argument("--garment", action="append", default=[], help="a garment material name prefix")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    poses = [{"name": p["name"], "bones": p["bones"]} for p in json.loads(args.poses.read_text())]
    report = measure(args.vrm, poses, args.garment)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    for garment, by_pose in report["garments"].items():
        print(garment)
        for pose, m in by_pose.items():
            print(f"  {pose:16} clearance {m['minClearanceMm']:7.1f} mm  inside {m['penetratingPct']:5.2f}%"
                  f"  deepest {m['maxPenetrationMm']:5.1f} mm  stretch {m['maxEdgeStretch']:5.2f}"
                  f" ({m['stretchedPct']:.2f}% > {STRETCHED})  {m['insideBy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
