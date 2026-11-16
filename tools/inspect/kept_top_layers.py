#!/usr/bin/env python3
"""KL3. Which layer is outermost, round her hips, where she keeps a top over new bottoms.

    python tools/inspect/kept_top_layers.py look.vrm [more.vrm ...] [--json out.json]

``keptTopTuck`` counts the vertices the pass moved. That is what the pass did, not what the
look looks like: a count of 6 "no room" vertices said nothing about a band of denim 19 mm
outside the cardigan's hem all along her front panels. This measures the picture instead.

Every surface (her kept top, the new bottom, the foundation under it, her skin) is sampled
about 2 mm apart and binned on a cylinder round her hip axis: 3 degree columns, 5 mm rows.
A cell's *outermost* layer is the one a camera level with it would see. Then, per zone
(front, left hip, right hip, back):

* ``bottomOverTop`` — cells where her top is and the bottom is outside it: denim drawn over
  the cardigan (the jeans hip split, and the front-hem band KL1 left);
* ``foundationThroughBottom`` — cells below her top's hem where the foundation is outside the
  bottom: briefs showing through the jeans;
* ``skinThroughBottom`` — the same for her skin: the bottom pulled into her;
* ``deepestBottomOverTopMm`` — how far outside, at worst.

Areas are in cm2 of that cylinder, so they are comparable between characters. A cell needs
``MIN_SAMPLES`` of a layer to count for it, and an excess under ``SEEN_M`` is not a showing
(two surfaces that close z-fight at worst; they do not read as one garment over another).

The hem is found per column (the lowest row her top reaches there): a cardigan's panels hang
lower at the front than its back does.

    python tools/inspect/kept_top_layers.py after.vrm --before before.vrm --poses POSES.json

``--before`` compares the bottom's own mesh with an earlier build of the same look, since a
correction that moves vertices must not cost the garment anything: the same vertices and
triangles (``sameTopology``), none collapsed (``degenerateTriangles``), none turned inside out
(``flippedTriangles``), seams still closed (``seamGapMm``: vertices that shared a position
still do), how far anything moved, how much an edge was stretched or squeezed, and what
happened to the waistband (its top 2 cm). ``--poses`` (HomePilot's presets) adds the bottom's
contact with her posed skin, standing and moving, from ``tools/inspect/pose_contact.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.garment_inventory import FOUNDATION_ROLES, garment_inventory  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402
from wardrobe.vrm.visible import visible_vertices  # noqa: E402

COLUMNS = 120
ROW_M = 0.005
SAMPLE_M = 0.002
MIN_SAMPLES = 3
#: An excess smaller than this is not one layer showing over another.
SEEN_M = 0.0015
#: Below the hem, this far down, is where a foundation or skin through the bottom is looked for.
BELOW_HEM_M = 0.12
ZONES = ("front", "leftHip", "back", "rightHip")
AREAS = ("topCm2", "bottomOverTopCm2", "foundationThroughBottomCm2", "skinThroughBottomCm2")


def _samples(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Points spread over the triangles about SAMPLE_M apart, and the vertices themselves."""
    if tris.size == 0:
        return points.astype(np.float64)
    a, b, c = (points[tris[:, k]].astype(np.float64) for k in range(3))
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    steps = np.clip(np.ceil(np.sqrt(area) / SAMPLE_M), 1, 40).astype(int)
    out = [points.astype(np.float64)]
    for n in np.unique(steps):
        rows = steps == n
        grid = np.array([(i / n, j / n) for i in range(n + 1) for j in range(n + 1 - i)])
        u, v = grid[:, 0][None, :, None], grid[:, 1][None, :, None]
        aa, bb, cc = a[rows][:, None, :], b[rows][:, None, :], c[rows][:, None, :]
        out.append((aa + (bb - aa) * u + (cc - aa) * v).reshape(-1, 3))
    return np.vstack(out)


def _world(document: GltfDocument, node_index: int, points: np.ndarray) -> np.ndarray:
    """Rest positions as drawn. A skinned mesh's vertices are already in the skeleton's space."""
    node = document.nodes[node_index]
    if "skin" in node:
        return points
    matrix = document.world_matrices()[node_index]
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def layers(document: GltfDocument) -> dict[str, np.ndarray]:
    """Surface samples per layer: ``top`` (kept, not a foundation), ``bottom`` (new, outer),
    ``foundation`` (Forge's, under it), ``skin`` (everything drawn that is not clothing or head)."""
    from wardrobe.engines.geometry_checks import body_points

    worn = garment_inventory(document)
    by_primitive = {(g.mesh, g.primitive): g for g in worn}
    out: dict[str, list[np.ndarray]] = {"top": [], "bottom": [], "foundation": []}
    textures: dict = {}
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        mesh_index = node["mesh"]
        for primitive_index, primitive in enumerate(document.meshes[mesh_index].get("primitives", [])):
            garment = by_primitive.get((mesh_index, primitive_index))
            if garment is None or primitive.get("indices") is None:
                continue
            if garment.role in FOUNDATION_ROLES:
                name = "foundation"
            elif garment.slot == "tops" and garment.role == "source":
                name = "top"
            elif garment.slot in ("bottoms", "onepiece") and garment.role != "source":
                name = "bottom"
            else:
                continue
            points = document.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
            tris = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            # As drawn: a VRoid top is cut out of its texture, and the sheet its alpha hides
            # reaches 6 cm below AvatarSample A's cardigan all round her hips.
            shown = visible_vertices(document, primitive, textures)
            if shown is not None:
                tris = tris[shown[tris].all(axis=1)]
            if tris.size == 0:
                continue
            used = np.unique(tris)
            remap = np.full(points.shape[0], -1)
            remap[used] = np.arange(used.size)
            out[name].append(_samples(_world(document, node_index, points[used]), remap[tris]))
    result = {name: (np.vstack(parts) if parts else np.zeros((0, 3))) for name, parts in out.items()}
    result["skin"] = body_points(document, skip=set(by_primitive), limit=400_000, spacing=SAMPLE_M)
    return result


def _field(points: np.ndarray, centre, forward: float, y0: float, rows: int):
    """(max radius, sample count) per (row, column). Column 0 is her back, COLUMNS/2 her front."""
    radius = np.full((rows, COLUMNS), np.nan)
    count = np.zeros((rows, COLUMNS), dtype=int)
    if points.shape[0] == 0:
        return radius, count
    dx, dz = points[:, 0] - centre[0], (points[:, 2] - centre[1]) * forward
    r = np.hypot(dx, dz)
    column = ((np.arctan2(dx, dz) + math.pi) / (2 * math.pi) * COLUMNS).astype(int) % COLUMNS
    row = np.floor((points[:, 1] - y0) / ROW_M).astype(int)
    ok = (row >= 0) & (row < rows)
    flat = row[ok] * COLUMNS + column[ok]
    count = np.bincount(flat, minlength=rows * COLUMNS).reshape(rows, COLUMNS)
    best = np.full(rows * COLUMNS, -np.inf)
    np.maximum.at(best, flat, r[ok])
    radius = np.where(count.ravel() > 0, best, np.nan).reshape(rows, COLUMNS)
    return radius, count


def zone_of(column: int) -> str:
    """Quarter turns centred on her front, sides and back."""
    turn = (column + 0.5) / COLUMNS  # 0 back, 0.5 front; x grows to her left in column order
    if 0.375 <= turn < 0.625:
        return "front"
    if 0.125 <= turn < 0.375:
        return "rightHip"
    if 0.625 <= turn < 0.875:
        return "leftHip"
    return "back"


def measure(path: Path) -> dict:
    document = GltfDocument.from_path(path)
    info = inspect_document(document)
    found = layers(document)
    report: dict = {"file": path.name, "samples": {k: int(v.shape[0]) for k, v in found.items()}}
    top, bottom = found["top"], found["bottom"]
    if top.shape[0] == 0 or bottom.shape[0] == 0:
        report["applicable"] = False
        report["reason"] = "no kept top" if top.shape[0] == 0 else "no new bottom"
        return report
    hips = document.node_world_position(info.humanoid_bones["hips"])
    centre = (float(hips[0]), float(hips[2]))
    forward = -1.0 if info.spec is VrmSpec.VRM0 else 1.0
    hem = float(top[:, 1].min())
    y0 = hem - BELOW_HEM_M
    y1 = min(float(top[:, 1].max()), float(bottom[:, 1].max()))
    rows = max(1, int(math.ceil((y1 - y0) / ROW_M)))
    fields = {name: _field(points, centre, forward, y0, rows) for name, points in found.items()}
    (top_r, top_n), (bottom_r, bottom_n) = fields["top"], fields["bottom"]
    (found_r, found_n), (skin_r, skin_n) = fields["foundation"], fields["skin"]
    has_top, has_bottom = top_n >= MIN_SAMPLES, bottom_n >= MIN_SAMPLES
    # Her top's hem, column by column: the lowest row it reaches there.
    hem_row = np.where(has_top.any(axis=0), has_top.argmax(axis=0), rows)
    row_index = np.arange(rows)[:, None]
    below_hem = row_index < hem_row[None, :]
    cell_cm2 = lambda r: r * (2 * math.pi / COLUMNS) * ROW_M * 1e4  # noqa: E731

    over_top = has_top & has_bottom & (bottom_r - top_r > SEEN_M)
    through = has_bottom & below_hem & (found_n >= MIN_SAMPLES) & (found_r - bottom_r > SEEN_M)
    skin_out = has_bottom & below_hem & (skin_n >= MIN_SAMPLES) & (skin_r - bottom_r > SEEN_M)
    zones = {zone: {"topCm2": 0.0, "bottomOverTopCm2": 0.0, "deepestBottomOverTopMm": 0.0,
                    "foundationThroughBottomCm2": 0.0, "skinThroughBottomCm2": 0.0} for zone in ZONES}
    for column in range(COLUMNS):
        zone = zones[zone_of(column)]
        for row in np.flatnonzero(has_top[:, column]):
            zone["topCm2"] += cell_cm2(top_r[row, column])
        for row in np.flatnonzero(over_top[:, column]):
            zone["bottomOverTopCm2"] += cell_cm2(top_r[row, column])
            excess = (bottom_r[row, column] - top_r[row, column]) * 1000
            zone["deepestBottomOverTopMm"] = max(zone["deepestBottomOverTopMm"], float(excess))
        for row in np.flatnonzero(through[:, column]):
            zone["foundationThroughBottomCm2"] += cell_cm2(bottom_r[row, column])
        for row in np.flatnonzero(skin_out[:, column]):
            zone["skinThroughBottomCm2"] += cell_cm2(bottom_r[row, column])
    for zone in zones.values():
        for key, value in zone.items():
            zone[key] = round(value, 1)
    # The hem band itself: the lowest 2 cm of her top in each column, where KL1 stopped.
    hem_band = has_top & (row_index >= hem_row[None, :]) & (row_index < hem_row[None, :] + 4)
    band_cells = int(hem_band.sum())
    band_over = int((hem_band & over_top).sum())
    report.update(
        applicable=True,
        spec="VRM0" if info.spec is VrmSpec.VRM0 else "VRM1",
        hemY=round(hem, 4),
        zones=zones,
        total={key: round(sum(zone[key] for zone in zones.values()), 1) for key in AREAS},
        deepestBottomOverTopMm=max(zone["deepestBottomOverTopMm"] for zone in zones.values()),
        hemBand={"cells": band_cells, "bottomOverTop": band_over,
                 "share": round(band_over / band_cells, 3) if band_cells else 0.0},
    )
    return report


def bottom_mesh(document: GltfDocument) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """The new bottom's own vertices and triangles (its primitives merged), and their names."""
    worn = {(g.mesh, g.primitive): g for g in garment_inventory(document)}
    points, tris, names, offset = [], [], [], 0
    for node_index in document.mesh_nodes():
        mesh_index = document.nodes[node_index]["mesh"]
        for primitive_index, primitive in enumerate(document.meshes[mesh_index].get("primitives", [])):
            garment = worn.get((mesh_index, primitive_index))
            if garment is None or garment.role in FOUNDATION_ROLES or garment.role == "source":
                continue
            if garment.slot not in ("bottoms", "onepiece") or primitive.get("indices") is None:
                continue
            p = document.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
            t = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            points.append(_world(document, node_index, p))
            tris.append(t + offset)
            offset += p.shape[0]
            names.append(garment.material)
    if not points:
        return None
    return np.vstack(points), np.vstack(tris), names


def _normals(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    return np.cross(points[tris[:, 1]] - points[tris[:, 0]], points[tris[:, 2]] - points[tris[:, 0]])


def _seams(points: np.ndarray) -> np.ndarray:
    """Index pairs of vertices that share a position (a UV or normal seam): they must stay together."""
    order = np.lexsort(np.round(points * 1e5).astype(np.int64).T)
    ordered = np.round(points[order] * 1e5).astype(np.int64)
    same = np.all(ordered[1:] == ordered[:-1], axis=1)
    return np.stack([order[:-1][same], order[1:][same]], axis=1)


def integrity(document: GltfDocument, before: GltfDocument | None = None) -> dict | None:
    """The bottom's mesh on its own, and against an earlier build of the same look."""
    found = bottom_mesh(document)
    if found is None:
        return None
    points, tris, names = found
    normals = _normals(points, tris)
    out = {"garment": names, "vertices": int(points.shape[0]), "triangles": int(tris.shape[0]),
           "degenerateTriangles": int((np.linalg.norm(normals, axis=1) < 1e-12).sum())}
    earlier = bottom_mesh(before) if before is not None else None
    if earlier is None:
        return out
    was, was_tris, _ = earlier
    same = was.shape == points.shape and np.array_equal(was_tris, tris)
    out["sameTopology"] = bool(same)
    if not same:
        return out
    moved = np.linalg.norm(points - was, axis=1)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    rest = np.linalg.norm(was[edges[:, 0]] - was[edges[:, 1]], axis=1)
    now = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    usable = rest > 1e-6
    ratio = now[usable] / rest[usable]
    was_normals = _normals(was, was_tris)
    seams = _seams(was)
    gap = np.linalg.norm(points[seams[:, 0]] - points[seams[:, 1]], axis=1) if seams.size else np.zeros(1)
    band = was[:, 1] >= was[:, 1].max() - 0.02
    out.update(
        movedVertices=int((moved > 1e-6).sum()),
        maxMoveMm=round(float(moved.max()) * 1000, 1),
        heightChangedMm=round(float(np.abs(points[:, 1] - was[:, 1]).max()) * 1000, 3),
        edgeRatio=[round(float(ratio.min()), 2), round(float(ratio.max()), 2)],
        flippedTriangles=int((np.einsum("ij,ij->i", normals, was_normals) < 0).sum()),
        seamPairs=int(seams.shape[0]),
        seamGapMm=round(float(gap.max()) * 1000, 3),
        waistband={"vertices": int(band.sum()), "moved": int((moved[band] > 1e-6).sum()),
                   "maxMoveMm": round(float(moved[band].max()) * 1000, 1) if band.any() else 0.0},
    )
    return out


def in_poses(path: Path, poses_file: Path, names: list[str], wanted: list[str]) -> dict:
    """The bottom against her posed skin (tools/inspect/pose_contact.py), worst of its primitives."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
    pose_contact = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pose_contact)
    presets = json.loads(poses_file.read_text())
    presets = presets["presets"] if isinstance(presets, dict) else presets
    poses = [pose for pose in presets if pose["name"] in wanted]
    measured = pose_contact.measure(path, poses, names)["garments"]
    out: dict = {}
    for by_pose in measured.values():
        for pose, m in by_pose.items():
            worst = out.setdefault(pose, dict.fromkeys(CONTACT, 0.0))
            for key in worst:
                worst[key] = max(worst[key], m[key])
    return out


POSES = ("standing", "standingBendForward", "sitting")
CONTACT = ("maxPenetrationMm", "penetratingPct", "maxEdgeStretch")
KEPT = ("total", "hemBand", "zones", "deepestBottomOverTopMm")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("looks", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--before", type=Path, default=None,
                        help="an earlier build of the same look (a file, or a folder of same-named files)")
    parser.add_argument("--poses", type=Path, default=None, help="HomePilot pose presets (JSON)")
    args = parser.parse_args()
    reports = []
    for path in args.looks:
        report = measure(path)
        earlier = None
        if args.before is not None:
            earlier = args.before / path.name if args.before.is_dir() else args.before
        if report.get("applicable"):
            document = GltfDocument.from_path(path)
            before = GltfDocument.from_path(earlier) if earlier is not None and earlier.is_file() else None
            report["mesh"] = integrity(document, before)
            if earlier is not None and earlier.is_file():
                report["before"] = {k: v for k, v in measure(earlier).items() if k in KEPT}
            if args.poses is not None and report["mesh"]:
                report["poses"] = in_poses(path, args.poses, report["mesh"]["garment"], list(POSES))
                if earlier is not None and earlier.is_file():
                    report["before"]["poses"] = in_poses(earlier, args.poses, report["mesh"]["garment"],
                                                         list(POSES))
        reports.append(report)
    for report in reports:
        if not report.get("applicable"):
            print(f"{report['file']}: not applicable ({report['reason']})")
            continue
        if report.get("before"):
            was = report["before"]
            share = was["hemBand"]["share"] * 100
            print(f"{report['file']}: BEFORE bottom over top {was['total']['bottomOverTopCm2']} cm2 "
                  f"(deepest {was['deepestBottomOverTopMm']} mm; hem band {share:.0f}%)")
        if report.get("mesh"):
            print(f"    mesh {json.dumps({k: v for k, v in report['mesh'].items() if k != 'garment'})}")
        if report.get("poses"):
            print(f"    poses {json.dumps(report['poses'])}")
        total, band = report["total"], report["hemBand"]
        print(f"{report['file']}: bottom over top {total['bottomOverTopCm2']} cm2 of {total['topCm2']} "
              f"(deepest {report['deepestBottomOverTopMm']} mm; hem band {band['share'] * 100:.0f}%), "
              f"foundation through bottom {total['foundationThroughBottomCm2']} cm2, "
              f"skin through bottom {total['skinThroughBottomCm2']} cm2")
        for name, zone in report["zones"].items():
            print(f"    {name:9} over top {zone['bottomOverTopCm2']:6} cm2 (deepest "
                  f"{zone['deepestBottomOverTopMm']:5} mm)  foundation "
                  f"{zone['foundationThroughBottomCm2']:5}  skin {zone['skinThroughBottomCm2']:5}")
    if args.json is not None:
        args.json.write_text(json.dumps(reports, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
