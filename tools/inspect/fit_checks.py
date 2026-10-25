"""SW2 QA. The six fit checks for one look in one pose: numbers and neutral technical panels.

    python tools/inspect/fit_checks.py LOOK.vrm [--before OLD.vrm] --pose sittingWide \\
        [--poses tests/fixtures/homepilot-poses.json] --out /tmp/qa/checks

``contact_sheet.py`` draws each garment alone, its wireframe and its clearance heatmap. This adds
what a picture of a garment cannot show, measured on the posed meshes the same way for every
file (so ``--before`` compares like with like):

1. **Gusset width** — the briefs' narrowest span across the crotch strip, station by station
   along its length, at rest and posed: the width the pattern drafted and the width it keeps.
2. **Leg openings** — each opening's edge loop (the boundary of the welded mesh, the waist
   excluded): its length posed against rest, its sharpest corner, and its clearance to her skin.
3. **Sections** — two planes: across her hip band (body, lingerie and dress as nested rings)
   and down through her thigh, beside the midline. Lines only; the plane through the thigh is
   off the midline on purpose, and nothing is drawn through her crotch.
4. **Topology** — connected parts and open edges (rest and posed are the same mesh, so these
   must not change), seam continuity (the largest gap between copies of a vertex a seam
   duplicates — any gap is a tear) and triangle inversions (a posed triangle whose normal
   faces against its own skinned frame).
5. **Contact** — clearance and penetration as ``pose_contact.py`` measures them; a shoe's foot
   and toes are left out, since her foot is meant to be inside it.
6. **Layers** — lingerie inside her skin, and dress inside the lingerie under it (within 15 mm,
   the reach a layer has over the next), counted and at their deepest.

Writes OUT/checks.json and OUT/sections.png, OUT/gusset.png and OUT/openings.png. OUT must be
outside the repository.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
pose_contact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pose_contact)

from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402
from wardrobe.vrm.weight_transfer import _nearest  # noqa: E402

WELD_M = 1e-4
PENETRATING_M = 0.001
LAYER_REACH_M = 0.015
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, INK, MUTED = (22, 24, 28), (236, 236, 236), (160, 166, 176)
COLOURS = {
    "body": (150, 150, 158),
    "lingerie": (255, 176, 92),
    "dress": (110, 168, 255),
    "other": (126, 232, 168),
}


def _font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------------------- load
def load(path: Path, pose: dict) -> dict:
    document = GltfDocument.from_bytes(path.read_bytes())
    info = inspect_document(document)
    arms = pose_contact.pose_deltas(document, info.humanoid_bones, pose["bones"], info.spec is VrmSpec.VRM0)
    names_of = pose_contact._humanoid_names(document, info.humanoid_bones)
    body_p, body_n, body_t, offset = [], [], [], 0
    garments = {}
    for name, node, attributes, points, tris in pose_contact._primitives(document):
        posed = pose_contact._posed(document, node, attributes, points, arms)
        if "_SKIN" in name or name == "Body":
            if "NORMAL" not in attributes:
                continue
            normals = document.read_accessor(attributes["NORMAL"]).astype(np.float64)
            moved = pose_contact._posed(document, node, attributes, points + normals * 0.01, arms) - posed
            body_p.append(posed)
            body_n.append(moved / np.maximum(np.linalg.norm(moved, axis=1, keepdims=True), 1e-9))
            body_t.append(tris + offset)
            offset += len(points)
            continue
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") != "garment":
            continue
        frames = _frames(document, node, attributes, arms)
        garments[name] = {
            "rest": points,
            "posed": posed,
            "tris": tris,
            "frames": frames,
            "role": tag.get("role"),
            "slot": str(tag.get("slot") or ""),
            "bones": pose_contact._dominant_bone(document, node, attributes, names_of),
        }
    hips = info.humanoid_bones.get("hips")
    hip = (
        (arms[hips] @ np.append(document.world_matrices()[hips][:3, 3], 1.0))[:3]
        if hips is not None
        else None
    )
    return {
        "body": (np.vstack(body_p), np.vstack(body_n), np.vstack(body_t)),
        "garments": garments,
        "hip": hip,
    }


def _frames(document, node, attributes, arms) -> np.ndarray:
    """(n, 3, 3) linear part of each vertex's skin transform."""
    skins = document.gltf.get("skins") or []
    joint_nodes = skins[node["skin"]].get("joints") or []
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    transforms = np.stack([arms.get(n, np.eye(4)) for n in joint_nodes])[:, :3, :3]
    total = np.maximum(weights.sum(axis=1), 1e-9)
    out = np.zeros((joints.shape[0], 3, 3))
    for slot in range(joints.shape[1]):
        out += (
            transforms[np.clip(joints[:, slot], 0, len(transforms) - 1)]
            * (weights[:, slot] / total)[:, None, None]
        )
    return out


def kind(name: str, garment: dict) -> str:
    if garment["role"] == "foundation":
        return "lingerie"
    if garment["slot"] in ("onepiece", "tops", "bottoms") and "Onepiece" in name:
        return "dress"
    return "other"


# ------------------------------------------------------------------------------------- metrics
def welded(points: np.ndarray) -> np.ndarray:
    keys = np.round(points / WELD_M).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    return ids.reshape(-1)


def topology(g: dict) -> dict:
    rest, posed, tris = g["rest"], g["posed"], g["tris"]
    ids = welded(rest)
    # Seam continuity: copies of one vertex must stay together.
    order = np.argsort(ids)
    gap = 0.0
    split = np.flatnonzero(np.diff(ids[order])) + 1
    for group in np.split(order, split):
        if len(group) > 1:
            gap = max(gap, float(np.ptp(posed[group], axis=0).max()))
    seams = int(sum(1 for group in np.split(order, split) if len(group) > 1))
    # Open edges on the welded mesh, and connected parts.
    wt = ids[tris]
    edges = np.sort(np.vstack([wt[:, [0, 1]], wt[:, [1, 2]], wt[:, [2, 0]]]), axis=1)
    edges = edges[edges[:, 0] != edges[:, 1]]
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique[counts == 1]
    parent = np.arange(ids.max() + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in unique:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    parts = len({find(v) for v in np.unique(wt)})

    # Inversions: a posed triangle facing against its own skinned frame.
    def normals(p):
        n = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)

    frame = g["frames"][tris].mean(axis=1)
    expected = np.einsum("nij,nj->ni", frame, normals(rest))
    area = np.linalg.norm(
        np.cross(rest[tris[:, 1]] - rest[tris[:, 0]], rest[tris[:, 2]] - rest[tris[:, 0]]), axis=1
    )
    usable = area > 1e-10
    inverted = int(((np.einsum("ij,ij->i", normals(posed), expected) < 0) & usable).sum())
    # Stretch, every edge counted.
    e = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    r = np.linalg.norm(rest[e[:, 0]] - rest[e[:, 1]], axis=1)
    p = np.linalg.norm(posed[e[:, 0]] - posed[e[:, 1]], axis=1)
    ratio = p[r > 1e-6] / r[r > 1e-6]
    return (
        {
            "vertices": len(rest),
            "triangles": len(tris),
            "connectedParts": parts,
            "openEdges": len(boundary),
            "seamGroups": seams,
            "seamGapMm": round(gap * 1000, 3),
            "invertedTriangles": inverted,
            "maxEdgeStretch": round(float(ratio.max()), 2),
            "edgesOver1_5Pct": round(float((ratio > 1.5).mean() * 100), 2),
        },
        boundary,
        ids,
    )


def contact(points: np.ndarray, body, keep=None) -> dict:
    cloud, normals, _ = body
    pts = points if keep is None else points[keep]
    index, _ = _nearest(pts, cloud, 1)
    signed = np.einsum("ij,ij->i", pts - cloud[index[:, 0]], normals[index[:, 0]])
    return {
        "minClearanceMm": round(float(signed.min()) * 1000, 1),
        "maxPenetrationMm": round(float(max(0.0, -signed.min())) * 1000, 1),
        "penetratingPct": round(float((signed < -PENETRATING_M).mean() * 100), 2),
    }


def layer_normals(points: np.ndarray, tris: np.ndarray, body) -> np.ndarray:
    n = np.zeros_like(points)
    face = np.cross(points[tris[:, 1]] - points[tris[:, 0]], points[tris[:, 2]] - points[tris[:, 0]])
    for k in range(3):
        np.add.at(n, tris[:, k], face)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    index, _ = _nearest(points, body[0], 1)
    if np.einsum("ij,ij->i", points - body[0][index[:, 0]], n).mean() < 0:
        n = -n
    return n


def between(outer: np.ndarray, inner: np.ndarray, inner_normals: np.ndarray) -> dict:
    index, dist = _nearest(outer, inner, 1)
    near = dist[:, 0] < LAYER_REACH_M
    signed = np.einsum("ij,ij->i", outer - inner[index[:, 0]], inner_normals[index[:, 0]])
    inside = near & (signed < -PENETRATING_M)
    return {
        "samplesWithin15mm": int(near.sum()),
        "insideCount": int(inside.sum()),
        "insidePct": round(float(inside.sum() / max(near.sum(), 1) * 100), 2),
        "deepestMm": round(float(max(0.0, -(signed[near].min() if near.any() else 0.0))) * 1000, 1),
    }


def gusset(g: dict) -> dict:
    """The crotch strip's width, cut plane by plane along its length (z), at rest and posed.

    Each station is a true section: every triangle of the strip that crosses the plane z = z0 at
    rest is cut there, and the same cut points (same edges, same fractions) are followed into the
    pose. Width is the distance between the outermost cut points; ``arc`` is the cloth's length
    across the strip along the cut, which is what a seat pulled in sideways loses first. A band of
    vertices instead of a cut reads a sparse mesh's two nearest vertices as the width.
    """
    rest, posed, tris = g["rest"], g["posed"], g["tris"]
    low = (rest[:, 1] < rest[:, 1].min() + 0.04) & (np.abs(rest[:, 0]) < 0.09)
    inside = tris[low[tris].all(axis=1)]
    if not len(inside):
        return {}
    zs = rest[np.unique(inside), 2]
    stations = []
    for z0 in np.arange(zs.min() + 0.003, zs.max(), 0.006):
        cuts = []
        for a, b in np.vstack([inside[:, [0, 1]], inside[:, [1, 2]], inside[:, [2, 0]]]):
            za, zb = rest[a, 2] - z0, rest[b, 2] - z0
            if za * zb >= 0 or za == zb:
                continue
            t = za / (za - zb)
            cuts.append((rest[a] + (rest[b] - rest[a]) * t, posed[a] + (posed[b] - posed[a]) * t))
        if len(cuts) < 2:
            continue
        cuts.sort(key=lambda c: c[0][0])
        r = np.array([c[0] for c in cuts])
        q = np.array([c[1] for c in cuts])
        stations.append(
            {
                "zMm": round(float(z0) * 1000, 1),
                "restMm": round(float(np.linalg.norm(r[-1] - r[0])) * 1000, 1),
                "posedMm": round(float(np.linalg.norm(q[-1] - q[0])) * 1000, 1),
                "restArcMm": round(float(np.linalg.norm(np.diff(r, axis=0), axis=1).sum()) * 1000, 1),
                "posedArcMm": round(float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum()) * 1000, 1),
            }
        )
    if not stations:
        return {}
    narrow = min(stations, key=lambda s: s["restMm"])
    return {
        "stations": stations,
        "narrowest": narrow,
        "minPosedMm": min(s["posedMm"] for s in stations),
        "worstRatio": round(min(s["posedMm"] / max(s["restMm"], 1e-6) for s in stations), 3),
    }


def loops(boundary: np.ndarray, ids: np.ndarray, g: dict, body) -> list[dict]:
    """Each open edge loop of the welded mesh, the waist excepted (the highest)."""
    rep = np.zeros(ids.max() + 1, dtype=np.int64)
    rep[ids] = np.arange(len(ids))
    adj: dict[int, list[int]] = {}
    for a, b in boundary:
        adj.setdefault(int(a), []).append(int(b))
        adj.setdefault(int(b), []).append(int(a))
    seen, out = set(), []
    for start in adj:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        if len(loop) > 8:
            out.append([rep[v] for v in loop])
    out.sort(key=lambda lp: g["rest"][lp, 1].mean())
    out = out[:-1] if len(out) > 1 else out  # the highest loop is the waist
    result = []
    for lp in out:

        def length(p, lp=lp):
            q = p[lp]
            return float(np.linalg.norm(np.diff(np.vstack([q, q[:1]]), axis=0), axis=1).sum())

        def corner(p, lp=lp):
            q = p[lp]
            a, b = np.roll(q, 1, axis=0) - q, np.roll(q, -1, axis=0) - q
            cos = np.einsum("ij,ij->i", a, b) / np.maximum(
                np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12
            )
            return float(np.degrees(np.arccos(np.clip(cos, -1, 1))).min())

        result.append(
            {
                "vertices": len(lp),
                "side": "left" if g["rest"][lp, 0].mean() < 0 else "right",
                "restLengthMm": round(length(g["rest"]) * 1000, 1),
                "posedLengthMm": round(length(g["posed"]) * 1000, 1),
                "sharpestCornerRestDeg": round(corner(g["rest"]), 1),
                "sharpestCornerPosedDeg": round(corner(g["posed"]), 1),
                "clearance": contact(g["posed"][lp], body),
                "indices": [int(v) for v in lp],
            }
        )
    return result


def check(path: Path, pose: dict, reference: dict | None = None) -> dict:
    data = load(path, pose)
    if reference is not None:
        # ``--baked``: a baked correction rewrites the bind geometry, so the corrected file's own rest is not
        # the pattern as drafted: measuring stretch, seams, gusset and openings against it would
        # compare each file with a different ruler. Every rest-based measure of the corrected
        # file is taken against the BEFORE file's rest and triangles, matched by primitive name;
        # only the posed positions come from the file being checked.
        for name, g in data["garments"].items():
            ref = reference["garments"].get(name)
            if ref is not None and len(ref["rest"]) == len(g["rest"]):
                g["rest"], g["tris"] = ref["rest"], ref["tris"]
    body = data["body"]
    report = {"file": path.name, "garments": {}, "layers": {}}
    surfaces = {}
    for name, g in data["garments"].items():
        short = name.split(" [")[0]
        topo, boundary, ids = topology(g)
        keep = (
            None
            if g["slot"] != "shoes"
            else np.array(["Foot" not in b and "Toe" not in b for b in g["bones"]])
        )
        entry = {"kind": kind(name, g), "topology": topo, "contact": contact(g["posed"], body, keep)}
        if "Brief" in short:
            entry["gusset"] = gusset(g)
            entry["legOpenings"] = loops(boundary, ids, g, body)
        report["garments"][short] = entry
        surfaces[short] = (g["posed"], layer_normals(g["posed"], g["tris"], body), entry["kind"], g)
    lingerie = [s for s in surfaces.items() if s[1][2] == "lingerie"]
    dresses = [s for s in surfaces.items() if s[1][2] == "dress"]
    for dname, (dp, _dn, _k, _g) in dresses:
        for lname, (lp, ln, _k2, _g2) in lingerie:
            report["layers"][f"{dname} inside {lname}"] = between(dp, lp, ln)
    for lname, _surface in lingerie:
        report["layers"][f"{lname} inside body"] = report["garments"][lname]["contact"]
    report["_data"] = data
    return report


# ---------------------------------------------------------------------------------------- draw
def section(points: np.ndarray, tris: np.ndarray, origin, normal, u, v) -> list[tuple]:
    """Segments where the plane (origin, normal) cuts the triangles, in plane coords (u, v)."""
    d = (points - origin) @ normal
    segs = []
    for t in tris:
        s = d[t]
        if (s > 0).all() or (s < 0).all():
            continue
        cut = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            if (s[i] > 0) != (s[j] > 0):
                w = s[i] / (s[i] - s[j])
                p = points[t[i]] + (points[t[j]] - points[t[i]]) * w
                cut.append(((p - origin) @ u, (p - origin) @ v))
        if len(cut) == 2:
            segs.append(tuple(cut))
    return segs


def draw_sections(reports: list[dict], out: Path) -> None:
    w, h = 900, 520
    image = Image.new("RGB", (w * 2, h * len(reports)), BG)
    draw = ImageDraw.Draw(image)
    for row, rep in enumerate(reports):
        data = rep["_data"]
        hip = data["hip"]
        body = data["body"]
        layers = [("body", body[0], body[2])] + [
            (kind(n, g), g["posed"], g["tris"]) for n, g in data["garments"].items() if kind(n, g) != "other"
        ]
        planes = [
            (
                "hip band, seen from above: body, lingerie and dress as nested rings",
                hip + np.array([0, 0.02, 0]),
                np.array([0, 1.0, 0]),
                np.array([1.0, 0, 0]),
                np.array([0, 0, 1.0]),
            ),
            (
                "down through her left thigh, beside the midline, seen from her side",
                hip + np.array([-0.09, 0, 0]),
                np.array([1.0, 0, 0]),
                np.array([0, 0, 1.0]),
                np.array([0, 1.0, 0]),
            ),
        ]
        for col, (title, origin, normal, u, v) in enumerate(planes):
            ox, oy = col * w + w // 2, row * h + h // 2 + 20
            scale = 1500 if col == 0 else 1100
            draw.text((col * w + 16, row * h + 10), f"{rep['file']} · {title}", font=_font(15), fill=INK)
            for name, pts, tris in layers:
                for a, b in section(pts, tris, origin, normal, u, v):
                    draw.line(
                        [(ox + a[0] * scale, oy - a[1] * scale), (ox + b[0] * scale, oy - b[1] * scale)],
                        fill=COLOURS[name],
                        width=2,
                    )
            ly = row * h + h - 70
            for name in ("body", "lingerie", "dress"):
                draw.rectangle((col * w + 16, ly, col * w + 30, ly + 12), fill=COLOURS[name])
                draw.text((col * w + 36, ly - 2), name, font=_font(13), fill=MUTED)
                ly += 18
            bar = scale * 0.01
            draw.line(
                [(col * w + w - 140, row * h + h - 30), (col * w + w - 140 + bar, row * h + h - 30)],
                fill=INK,
                width=2,
            )
            draw.text((col * w + w - 140, row * h + h - 50), "10 mm", font=_font(12), fill=MUTED)
    image.save(out)


def draw_gusset(reports: list[dict], out: Path) -> None:
    image = Image.new("RGB", (900, 420), BG)
    draw = ImageDraw.Draw(image)
    draw.text(
        (16, 10),
        "Gusset width along the crotch strip (stations every 6 mm, front to back)",
        font=_font(16),
        fill=INK,
    )
    colours = [(126, 232, 168), (255, 176, 92), (110, 168, 255)]
    series = []
    for rep in reports:
        for g in rep["garments"].values():
            if g.get("gusset", {}).get("stations"):
                st = g["gusset"]["stations"]
                if not series:
                    series.append(("rest (as drafted)", [s["restMm"] for s in st]))
                series.append((f"posed · {rep['file']}", [s["posedMm"] for s in st]))
    if not series:
        image.save(out)
        return
    top = max(max(vals) for _, vals in series) * 1.15
    x0, y0, plot_w, plot_h = 70, 360, 780, 300
    draw.line([(x0, y0), (x0 + plot_w, y0)], fill=MUTED)
    draw.line([(x0, y0), (x0, y0 - plot_h)], fill=MUTED)
    for mm in range(0, int(top) + 1, 20):
        y = y0 - mm / top * plot_h
        draw.text((20, y - 7), f"{mm}", font=_font(12), fill=MUTED)
        draw.line([(x0, y), (x0 + plot_w, y)], fill=(40, 42, 48))
    for k, (label, vals) in enumerate(series):
        xs = [x0 + plot_w * i / max(len(vals) - 1, 1) for i in range(len(vals))]
        ys = [y0 - val / top * plot_h for val in vals]
        draw.line(list(zip(xs, ys, strict=True)), fill=colours[k % 3], width=3)
        draw.rectangle((x0 + 10, 40 + 18 * k, x0 + 24, 52 + 18 * k), fill=colours[k % 3])
        draw.text((x0 + 30, 38 + 18 * k), label, font=_font(13), fill=INK)
    draw.text((x0, y0 + 10), "front", font=_font(12), fill=MUTED)
    draw.text((x0 + plot_w - 30, y0 + 10), "back", font=_font(12), fill=MUTED)
    image.save(out)


def draw_openings(reports: list[dict], out: Path) -> None:
    w, h = 900, 460
    image = Image.new("RGB", (w, h * len(reports)), BG)
    draw = ImageDraw.Draw(image)
    for row, rep in enumerate(reports):
        data = rep["_data"]
        draw.text(
            (16, row * h + 10),
            f"{rep['file']} · briefs' leg openings, garment only, seen from her side; "
            "dots: seam (welded) vertices on the loop",
            font=_font(14),
            fill=INK,
        )
        for name, g in rep["garments"].items():
            for lp in g.get("legOpenings", []):
                full = data["garments"][[n for n in data["garments"] if n.startswith(name)][0]]
                q = full["posed"][lp["indices"]]
                hip = data["hip"]
                ox, oy, scale = (w // 4 if lp["side"] == "left" else 3 * w // 4), row * h + h // 2, 1600
                pts = [(ox + (p[2] - hip[2]) * scale, oy - (p[1] - hip[1] + 0.09) * scale) for p in q]
                draw.line(pts + pts[:1], fill=COLOURS["lingerie"], width=2)
                for p in pts[:: max(len(pts) // 24, 1)]:
                    draw.ellipse((p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3), fill=INK)
                c = lp["clearance"]
                draw.text(
                    (ox - 180, row * h + h - 60),
                    f"{lp['side']}: {lp['vertices']} verts · "
                    f"length {lp['restLengthMm']} → {lp['posedLengthMm']} mm",
                    font=_font(12),
                    fill=MUTED,
                )
                draw.text(
                    (ox - 180, row * h + h - 42),
                    f"sharpest corner {lp['sharpestCornerPosedDeg']}° · "
                    f"deepest inside {c['maxPenetrationMm']} mm",
                    font=_font(12),
                    fill=MUTED,
                )
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("look", type=Path)
    parser.add_argument("--before", type=Path, default=None)
    parser.add_argument(
        "--baked",
        action="store_true",
        help="LOOK is BEFORE with a pose's correction baked in (bake_pose_correction.py): "
        "measure both against BEFORE's rest geometry",
    )
    parser.add_argument("--pose", default="sittingWide")
    parser.add_argument("--poses", type=Path, default=ROOT / "tests/fixtures/homepilot-poses.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; QA output is written outside it")
    out.mkdir(parents=True, exist_ok=True)
    pose = {p["name"]: p for p in json.loads(args.poses.read_text())["presets"]}[args.pose]
    files = [args.before, args.look] if args.before else [args.look]
    reports = []
    for f in files:
        reports.append(check(f, pose, reports[0]["_data"] if reports and args.baked else None))
    draw_sections(reports, out / "sections.png")
    draw_gusset(reports, out / "gusset.png")
    draw_openings(reports, out / "openings.png")
    clean = []
    for rep in reports:
        rep = {k: v for k, v in rep.items() if k != "_data"}
        for g in rep["garments"].values():
            for lp in g.get("legOpenings", []):
                lp.pop("indices", None)
        clean.append(rep)
    (out / "checks.json").write_text(json.dumps({"pose": args.pose, "files": clean}, indent=1))
    print(json.dumps({"pose": args.pose, "files": clean}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
