"""LC2. A collection piece's finishing, built on the garment after it is fitted.

A pattern block makes the panels: cups, band, brief, straps. What makes a lingerie set
read as *made* is what a workroom adds to those panels afterwards — lace appliqué along
chosen edges, narrow elastic binding round the cups, a satin bow at the centre and the
hips, metal on the straps — and every one of those is sewn to the fabric where the
fabric actually is. So they are built here, after the shell and the lingerie seating
(``wardrobe.engines.shell``), from the fitted mesh's own vertices and normals:

* a **lace band** is a strip laid across the fabric from an edge inward, ``widthMm``
  wide, each row projected back onto the fitted surface and lifted a fraction of a
  millimetre off it. Built from the draft instead, it floated where the brief's panels
  had been before the conform pass moved them, or sank into them;
* **binding** is a 4 mm ribbon along a cup edge, on the edge's own fitted vertices;
* **bows**, the **charm**, the **rings and sliders** are rigid parts placed at points the
  fitted garment publishes (the gore's top, the front hip where a thong's string leaves
  its panel, a point along each strap's fitted path) by the hardware kit's ``place``.

Every triangle, the panels' and the finishing's, is then tagged with a named component
(``bra_left_cup``, ``bottom_lace``, ``bow_L`` …) and the material it is made of. The
components stay one skinned garment — one node, as every garment the Forge makes, so
garment inventory, layering and the adult gate see a bra and a bottom and nothing else —
and the assembly gives each material its own primitive (``wardrobe.lingerie.assembly``);
the node's extras list the components by name, so a downstream tool can find
``bra_strap_L`` without guessing from triangles.

Left and right are hers: on a VRM 1.0 avatar (facing +Z) her left is +X, on a VRM 0.x
avatar (facing -Z) it is -X, so sides are computed from ``forward``, never from x alone.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh, section_ranges
from wardrobe.geometry.ribbon import ribbon

#: How far finishing sits off the fabric under it: lace and binding are sewn on top.
LACE_LIFT_M = 0.0007
BINDING_LIFT_M = 0.0011
#: Rows across a lace band; one lace tile along it covers this much edge.
LACE_ROWS = 4
LACE_TILE_M = 0.05
#: Binding and the Brazilian's centre seam.
BINDING_THICKNESS_M = 0.0008
SEAM_WIDTH_M = 0.0018
#: A lace band narrows to nothing over this fraction of a cup's outer edge, from the peak.
PEAK_TAPER = 0.35
#: Hardware is not graded: a slider is a slider on anyone. Scale of the hosiery kit's parts.
BRA_HARDWARE_SCALE = 0.75
#: Where along each strap (front anchor 0 → back 1) the ring and the slider sit.
RING_AT, SLIDER_AT = 0.02, 0.1
BASE_HEIGHT_M = 1.68

#: Component → the material it is made of (wardrobe.lingerie.assembly).
MATERIALS = ("mesh", "band", "lining", "elastic", "lace", "satin", "metal")


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------
def embellish(mesh: Mesh, collection: dict, params) -> Mesh:
    """The fitted piece with its finishing, and every triangle tagged with its component."""
    forward = float(getattr(params, "forward", 1.0) or 1.0)
    grade = float(params.height) / BASE_HEIGHT_M
    frame = mesh.metadata.get("lingerieFrame") or {}
    centre_x = float((frame.get("lingerieLandmarks") or {}).get("centre_x", 0.0))
    positions = mesh.positions.astype(np.float64)
    normals = mesh.normals.astype(np.float64)
    tris = mesh.indices.reshape(-1, 3).astype(np.int64)
    ctx = _Ctx(positions, normals, tris, forward, centre_x, _ring_centre_z(mesh, positions), grade)

    names, materials = _classify(mesh, collection, ctx)
    if collection.get("dots"):
        # LC3. Flock dots, projected straight onto her from the front and back: the panels'
        # own UVs run round her row by row and shear across the seat, which drew the dots
        # as diagonal streaks. Dots are round where the product is looked at.
        from wardrobe.lingerie.fabrics import DOT_TILE_M

        mesh.uvs = (positions[:, :2] / DOT_TILE_M).astype(np.float32)
    pieces: list[tuple[str, str, Mesh]] = []
    if collection.get("piece") == "bra":
        pieces += _bra_finishing(mesh, collection, ctx)
    else:
        pieces += _bottom_finishing(mesh, collection, ctx)

    return _assemble(mesh, names, materials, pieces)


def _ring_centre_z(mesh: Mesh, positions: np.ndarray) -> float:
    """Front-to-back middle of the ring the piece goes round her by: its waist row, or its band.

    The median of every vertex was not it: a thong is nearly all front panel, so its
    median sat in front of her and the lower front, curving under her, read as "back".
    """
    brief = mesh.metadata.get("lingerieBrief") or {}
    bra = mesh.metadata.get("lingerieBra") or {}
    ring = brief.get("waist") or ((bra.get("bandRows") or [None])[0])
    if ring:
        z = positions[[int(v) for v in ring], 2]
        return float((z.max() + z.min()) / 2)
    return float(np.median(positions[:, 2]))


class _Ctx:
    def __init__(self, positions, normals, tris, forward, centre_x, centre_z, grade):
        self.positions, self.normals, self.tris = positions, normals, tris
        self.forward, self.centre_x, self.centre_z, self.grade = forward, centre_x, centre_z, grade

    def side_of(self, x: float) -> str:
        """Her side for a point at ``x``: "L" or "R"."""
        return "L" if (x - self.centre_x) * self.forward > 0 else "R"

    def is_front(self, z: np.ndarray) -> np.ndarray:
        return (np.asarray(z) - self.centre_z) * self.forward > 0


# ----------------------------------------------------------------------
# the panels: which component, which material
# ----------------------------------------------------------------------
def _classify(mesh: Mesh, collection: dict, ctx: _Ctx) -> tuple[list[str], list[str]]:
    count = ctx.tris.shape[0]
    centroid = ctx.positions[ctx.tris].mean(axis=1)
    side = np.where((centroid[:, 0] - ctx.centre_x) * ctx.forward > 0, "L", "R")
    front = ctx.is_front(centroid[:, 2])
    names = ["" for _ in range(count)]
    materials = ["mesh" for _ in range(count)]
    for section, first, n in section_ranges(mesh):
        for t in range(first, first + n):
            names[t], materials[t] = _component(section, collection, bool(front[t]), str(side[t]),
                                                centroid[t], ctx)
    strings = _string_triangles(mesh, ctx)
    for t in np.flatnonzero(strings):
        if materials[t] == "mesh":
            materials[t] = "elastic"
    return names, materials


#: A brief's panel narrower than this, waist to leg, is its elastic: a string side, a
#: thong's back. Drawn in the sheer mesh it read as see-through wedges at her hips.
STRING_M = 0.014


def _string_triangles(mesh: Mesh, ctx: _Ctx) -> np.ndarray:
    record = mesh.metadata.get("lingerieBrief") or {}
    out = np.zeros(ctx.tris.shape[0], dtype=bool)
    if not record:
        return out
    rows, columns = int(record["rows"]), int(record["columns"])
    limit = (rows + 1) * columns
    heights = np.array([ctx.positions[j][1] - ctx.positions[rows * columns + j][1] for j in range(columns)])
    narrow = np.zeros(ctx.positions.shape[0], dtype=bool)
    narrow[:limit] = np.tile(heights < STRING_M, rows + 1)
    return np.all(narrow[ctx.tris], axis=1)


def _component(section: str, collection: dict, front: bool, side: str, centroid: np.ndarray,
               ctx: _Ctx) -> tuple[str, str]:
    if collection.get("piece") == "bra":
        if section.startswith("strap"):
            return f"bra_strap_{side}", "elastic"
        if section == "bra-cups":
            return ("bra_left_cup" if side == "L" else "bra_right_cup"), "mesh"
        if section.startswith("elastic"):
            return ("bra_underband" if front else "bra_back_band"), "elastic"
        return ("bra_underband" if front else "bra_back_band"), "band"
    # A bottom: the gusset is lined (opaque), the elastics are elastic, the rest is mesh.
    if section == "gusset":
        return "bottom_gusset", "lining"
    material = "elastic" if section.startswith("elastic") else "mesh"
    angle = math.degrees(math.atan2((centroid[0] - ctx.centre_x) * ctx.forward,
                                    (centroid[2] - ctx.centre_z) * ctx.forward))
    if abs(angle) < 55.0:
        return "bottom_front", material
    if abs(angle) > 125.0:
        thong = collection.get("bottomStyle") == "thong"
        return ("thong_back_strap" if thong else "bottom_back"), material
    return f"bottom_side_{side}", material


# ----------------------------------------------------------------------
# the bra's finishing
# ----------------------------------------------------------------------
def _bra_finishing(mesh: Mesh, collection: dict, ctx: _Ctx) -> list[tuple[str, str, Mesh]]:
    record = mesh.metadata.get("lingerieBra") or {}
    cups = record.get("cups") or {}
    pieces: list[tuple[str, str, Mesh]] = []
    cup_tris = _section_triangles(mesh, "bra-cups")
    lace = collection.get("lace") or {}
    binding = collection.get("binding") or {}
    for cup in cups.values():
        rows = [list(map(int, row)) for row in cup["rows"]]
        side = ctx.side_of(float(np.mean(ctx.positions[rows[0], 0])))
        outer = [row[-1] for row in rows]          # band → peak
        inner = [row[0] for row in rows]           # gore → peak
        lower = rows[0]                            # inner → outer, along the band's top
        edges = {"cup-outer": outer[::-1], "cup-inner": inner[::-1], "cup-lower": lower[::-1]}
        if lace.get("edges"):
            # One band: down the outer edge from the peak, round the corner, along the
            # bottom to the gore — as galloon lace is sewn, in one piece.
            path: list[int] = []
            for name in ("cup-outer", "cup-lower"):
                if name in lace["edges"]:
                    ids = edges[name]
                    path += ids if not path else ids[1:]
            width = float(lace.get("widthMm", 24)) / 1000.0 * ctx.grade
            taper = _peak_taper(ctx.positions[path], len(outer) if "cup-outer" in lace["edges"] else 0)
            band = lace_band(path, ctx, cup_tris, width * taper, name=f"bra_lace_{side}",
                             clear_of=ctx.positions[inner[1:]])
            if band is not None:
                pieces.append((f"bra_lace_{side}", "lace", band))
        for name in binding.get("edges") or []:
            ids = edges.get(name)
            if ids:
                trim = _binding(ids, ctx, float(binding.get("widthMm", 4)) / 1000.0, f"bra_binding_{side}")
                pieces.append((f"bra_binding_{side}", "elastic", trim))
    for bow in collection.get("bows") or []:
        if bow.get("at") == "centre-front":
            at = _gore_top(record, ctx)
            if at is not None:
                size = float(bow.get("sizeMm", 13)) / 1000.0
                pieces.append(("bow_center", "satin", _place_bow(at, ctx, size, "bow_center")))
    hardware = collection.get("hardware") or {}
    if hardware:
        pieces += _strap_hardware(mesh, ctx, hardware)
    return pieces


def _peak_taper(points: np.ndarray, outer_count: int) -> np.ndarray:
    """1 along the band, easing to 0 toward a cup's peak over its outer edge's first stretch."""
    taper = np.ones(points.shape[0])
    if outer_count < 2:
        return taper
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points[:outer_count], axis=0), axis=1))])
    ramp = max(along[-1] * PEAK_TAPER, 1e-6)
    t = np.clip(along / ramp, 0.0, 1.0)
    taper[:outer_count] = t * t * (3 - 2 * t)
    return np.maximum(taper, 0.08)


def _gore_top(record: dict, ctx: _Ctx):
    """The point between her cups where the band's top is highest: the gore's centre."""
    rows = record.get("bandRows")
    front = int(record.get("frontColumns") or 0)
    if not rows or front < 3:
        return None
    top = list(map(int, rows[-1][:front]))
    points = ctx.positions[top]
    middle = top[int(np.argmin(np.abs(points[:, 0] - ctx.centre_x)))]
    return middle


def _strap_hardware(mesh: Mesh, ctx: _Ctx, hardware: dict) -> list[tuple[str, str, Mesh]]:
    from wardrobe.hosiery.hardware import place, ring_local, slider_local

    out = []
    for section, first, count in section_ranges(mesh):
        if not section.startswith("strap") or count == 0:
            continue
        ids = ctx.tris[first:first + count].reshape(-1)
        lo, hi = int(ids.min()), int(ids.max()) + 1
        if (hi - lo) % 4:
            continue
        # A ribbon is four vertices per path point (wardrobe.geometry.ribbon), front anchor first.
        group = ctx.positions[lo:hi].reshape(-1, 4, 3)
        path = group.mean(axis=1)
        face = ctx.normals[lo:hi].reshape(-1, 4, 3).mean(axis=1)
        along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
        for kind, fraction in (("ring", RING_AT), ("slider", SLIDER_AT)):
            if not hardware.get(kind):
                continue
            s = along[-1] * fraction
            i = int(np.clip(np.searchsorted(along, s), 1, path.shape[0] - 1))
            origin = path[i]
            up = path[min(i + 1, path.shape[0] - 1)] - path[i - 1]
            normal = face[i] / max(np.linalg.norm(face[i]), 1e-9)
            local = (ring_local if kind == "ring" else slider_local)()
            local.positions = (local.positions * BRA_HARDWARE_SCALE).astype(np.float32)
            across = np.cross(up, normal)
            part = place(local, origin + normal * 0.0012, across, up, normal, f"hardware-{kind}")
            out.append(("hardware", "metal", part))
    return out


# ----------------------------------------------------------------------
# the bottom's finishing
# ----------------------------------------------------------------------
def _bottom_finishing(mesh: Mesh, collection: dict, ctx: _Ctx) -> list[tuple[str, str, Mesh]]:
    record = mesh.metadata.get("lingerieBrief") or {}
    if not record:
        return []
    rows, columns = int(record["rows"]), int(record["columns"])
    panel_limit = (rows + 1) * columns  # vertices past this are the gusset's
    panel_tris = _panel_triangles(mesh)
    pieces: list[tuple[str, str, Mesh]] = []
    lace = collection.get("lace") or {}
    width = float(lace.get("widthMm", 22)) / 1000.0 * ctx.grade
    edges = set(lace.get("edges") or [])
    # Every open edge of the panels: waist and both leg openings (the gusset's excepted).
    boundary = [int(v) for v in record["waist"]] + [
        int(v) for loop in (record.get("legOpenings") or {}).values() for v in loop if int(v) < panel_limit]
    if edges & {"legs", "front-legs"}:
        for loop in (record.get("legOpenings") or {}).values():
            ids = [int(v) for v in loop if int(v) < panel_limit]
            if "front-legs" in edges and "legs" not in edges:
                ids = _front_run(ids, record)
            for run in _runs(ids, ctx, gap=0.2):
                band = lace_band(run, ctx, panel_tris, np.full(len(run), width), name="bottom_lace",
                                 clear_of=_others(boundary, run, ctx))
                if band is not None:
                    pieces.append(("bottom_lace", "lace", band))
    if "front-waist" in edges:
        waist = [int(v) for v in record["waist"]]
        corners = _front_hips(record, ctx)
        if corners:
            lo, hi = sorted(waist.index(c) for c in corners.values())
            run = waist[lo:hi + 1]
            band = lace_band(run, ctx, panel_tris, np.full(len(run), width * 0.85), name="bottom_lace",
                             clear_of=_others(boundary, run, ctx))
            if band is not None:
                pieces.append(("bottom_lace", "lace", band))
    corners = _front_hips(record, ctx)
    for bow in collection.get("bows") or []:
        if bow.get("at") in ("hips", "hips-front") and corners:
            size = float(bow.get("sizeMm", 15)) / 1000.0
            for side, vertex in corners.items():
                pieces.append((f"bow_{side}", "satin", _place_bow(vertex, ctx, size, f"bow_{side}")))
    charm = collection.get("charm")
    if charm and record.get("centreFront") is not None:
        pieces.append(("charm", "metal", _place_charm(int(record["centreFront"]), ctx)))
    if collection.get("centreSeam") and record.get("centreBack") is not None:
        column = int(record["centreBack"]) % columns
        ids = [k * columns + column for k in range(rows + 1)]
        pieces.append(("bottom_back_seam", "elastic", _binding(ids, ctx, SEAM_WIDTH_M, "bottom_back_seam")))
    return pieces


def _others(boundary: list[int], run: list[int], ctx: _Ctx, near: float = 0.012) -> np.ndarray:
    """The boundary's points that are not this run, nor within ``near`` of its ends."""
    mine = set(run)
    ends = ctx.positions[[run[0], run[-1]]]
    rest = [v for v in dict.fromkeys(boundary) if v not in mine]
    if not rest:
        return np.zeros((0, 3))
    points = ctx.positions[rest]
    keep = np.min(np.linalg.norm(points[:, None, :] - ends[None, :, :], axis=2), axis=1) > near
    return points[keep]


def _front_hips(record: dict, ctx: _Ctx) -> dict[str, int]:
    """Where the front panel's top meets the side (a thong's string): one waist vertex per side.

    Walking out from centre front along the waistline, the panel is as tall as the
    distance from its waist row to its leg row in that column; the corner is the last
    column before that falls to a side's height. Measured on the fitted panel, so the
    bow sits on the corner the fabric actually has.
    """
    rows, columns = int(record["rows"]), int(record["columns"])
    waist = [int(v) for v in record["waist"]]
    p = ctx.positions
    heights = np.array([p[k][1] - p[rows * columns + j][1] for j, k in enumerate(waist)])
    centre = waist.index(int(record["centreFront"])) if int(record["centreFront"]) in waist else None
    if centre is None:
        return {}
    sides = [int(v) for v in (record.get("sideAnchors") or {}).values() if int(v) < columns]
    side_height = float(np.mean(heights[sides])) if sides else float(heights.min())
    # The corner: where the panel has narrowed most of the way from its centre to a side.
    limit = side_height + 0.3 * (heights[centre] - side_height)
    out: dict[str, int] = {}
    for step in (-1, 1):
        j = centre
        while 0 < j + step < columns - 1 and heights[j + step] > limit:
            j += step
        out[ctx.side_of(float(p[waist[j]][0]))] = waist[j]
    return out if len(out) == 2 else {}


def _front_run(ids: list[int], record: dict) -> list[int]:
    """The front half of a leg opening, by the pattern's own columns: side seam to side seam."""
    columns = int(record["columns"])
    right_side = int((record.get("sideAnchors") or {}).get("positiveX", columns // 2))
    return [v for v in ids if (v % columns) <= right_side]


def _runs(ids: list[int], ctx: _Ctx, gap: float = 0.03) -> list[list[int]]:
    """Split a vertex list into runs wherever consecutive points are further apart than ``gap``."""
    runs, current = [], []
    for v in ids:
        if current and np.linalg.norm(ctx.positions[v] - ctx.positions[current[-1]]) > gap:
            runs.append(current)
            current = []
        current.append(v)
    if current:
        runs.append(current)
    return [r for r in runs if len(r) >= 3]


# ----------------------------------------------------------------------
# builders
# ----------------------------------------------------------------------
def lace_band(edge: list[int], ctx: _Ctx, region: np.ndarray, widths: np.ndarray, *,
              name: str = "lace", clear_of: np.ndarray | None = None) -> Mesh | None:
    """A strip of lace from an edge across the fabric, on its fitted surface.

    ``region`` is the triangles the band lies over (a cup, a brief's panels): the
    direction "into the garment" at each edge vertex is toward the mean of its
    neighbours in those triangles, so a band along a cup's lower edge goes up into the
    cup and not down into the band it shares that edge with.

    ``clear_of`` is the panel's other edges: the band is never wider than ``FILL`` of the
    way to the nearest of them. A thong's front narrows to a few centimetres at the
    gusset, a Brazilian's side to twelve millimetres, and a band of constant width
    there ran past the far edge and stood off her as a flap.
    """
    if len(edge) < 3:
        return None
    edge = list(dict.fromkeys(edge))
    points = ctx.positions[edge]
    normals = ctx.normals[edge]
    tangent = np.gradient(points, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    inward = _inward(edge, region, ctx)
    inward -= tangent * np.sum(inward * tangent, axis=1, keepdims=True)
    inward -= normals * np.sum(inward * normals, axis=1, keepdims=True)
    inward /= np.maximum(np.linalg.norm(inward, axis=1, keepdims=True), 1e-12)
    widths = np.asarray(widths, dtype=np.float64)[: len(edge)]
    # An even spacing along the edge: a thong's leg line drops steeply into the gusset, its
    # last columns centimetres apart, and a band drawn vertex to vertex cut that corner.
    points, normals, inward, widths = _resample(points, [normals, inward, widths[:, None]], LACE_STEP_M)
    widths = widths[:, 0]
    if clear_of is not None and len(clear_of):
        gap = np.min(np.linalg.norm(points[:, None, :] - np.asarray(clear_of)[None, :, :], axis=2), axis=1)
        widths = np.minimum(widths, FILL * gap)
    region_tris = ctx.tris[region] if region.size else ctx.tris
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    n_points = points.shape[0]
    grid, uvs = [], []
    for k in range(LACE_ROWS + 1):
        t = k / LACE_ROWS
        q = points + inward * (widths * t)[:, None]
        q = _onto(q, ctx, region_tris, LACE_LIFT_M) if k else points + normals * LACE_LIFT_M
        grid.append(q)
        uvs.append(np.column_stack([along / LACE_TILE_M, np.full(n_points, t)]))
    vertices = np.vstack(grid)
    n = points.shape[0]
    faces = []
    for k in range(LACE_ROWS):
        for i in range(n - 1):
            a, b = k * n + i, k * n + i + 1
            c, d = (k + 1) * n + i + 1, (k + 1) * n + i
            faces += [(a, b, c), (a, c, d)]
    band = Mesh(positions=vertices.astype(np.float32), indices=np.array(faces, dtype=np.uint32).reshape(-1),
                uvs=np.vstack(uvs).astype(np.float32), metadata={"section": name})
    band.compute_normals()
    _face_out(band, np.tile(normals, (LACE_ROWS + 1, 1)))
    return band


#: A lace band's edge is resampled to this spacing, and fills at most this much of the way
#: to the panel's nearest other edge.
LACE_STEP_M = 0.005
FILL = 0.45


def _resample(points: np.ndarray, attributes: list[np.ndarray], step: float):
    """``points`` (a polyline) at an even ``step``, with per-point ``attributes`` interpolated."""
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    count = max(int(np.ceil(along[-1] / step)) + 1, 3)
    at = np.linspace(0.0, along[-1], count)
    out = [np.column_stack([np.interp(at, along, points[:, k]) for k in range(points.shape[1])])]
    for values in attributes:
        values = np.asarray(values, dtype=np.float64)
        out.append(np.column_stack([np.interp(at, along, values[:, k]) for k in range(values.shape[1])]))
    for k in (1, 2):  # normals and inward directions stay unit length
        out[k] /= np.maximum(np.linalg.norm(out[k], axis=1, keepdims=True), 1e-12)
    return tuple(out)


def _binding(ids: list[int], ctx: _Ctx, width: float, name: str) -> Mesh:
    ids = list(dict.fromkeys(ids))
    path = ctx.positions[ids] + ctx.normals[ids] * BINDING_LIFT_M
    return ribbon(path, ctx.normals[ids], width=width, thickness=BINDING_THICKNESS_M, name=name)


def _inward(edge: list[int], region: np.ndarray, ctx: _Ctx) -> np.ndarray:
    tris = ctx.tris[region] if region.size else ctx.tris
    total = np.zeros((ctx.positions.shape[0], 3))
    count = np.zeros(ctx.positions.shape[0])
    for a, b in ((0, 1), (1, 2), (2, 0)):
        np.add.at(total, tris[:, a], ctx.positions[tris[:, b]])
        np.add.at(count, tris[:, a], 1)
        np.add.at(total, tris[:, b], ctx.positions[tris[:, a]])
        np.add.at(count, tris[:, b], 1)
    edge = np.asarray(edge)
    mean = total[edge] / np.maximum(count[edge], 1)[:, None]
    return mean - ctx.positions[edge]


def _onto(points: np.ndarray, ctx: _Ctx, tris: np.ndarray, lift: float) -> np.ndarray:
    """Each point moved to the closest point on the fabric's triangles, then lifted off it.

    Exactly onto the triangles, not onto a tangent plane at the nearest vertex: where a
    thong's front curves under her into the gusset the plane of the nearest vertex is
    steep, and lace "projected" onto it stood a centimetre off the fabric as a flap.
    """
    a, b, c = (ctx.positions[tris[:, k]] for k in range(3))
    face_n = np.cross(b - a, c - a)
    face_n /= np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-12)
    vertex_n = ctx.normals[tris].mean(axis=1)
    flip = np.sum(face_n * vertex_n, axis=1) < 0  # face the way the fabric's normals do
    face_n[flip] *= -1
    centroid = (a + b + c) / 3
    out = np.empty_like(points)
    for start in range(0, points.shape[0], 128):
        q = points[start:start + 128]
        # The 12 nearest triangles by centroid, then the exact closest point on each.
        near = np.argsort(np.linalg.norm(q[:, None, :] - centroid[None, :, :], axis=2), axis=1)[:, :12]
        best = _closest_on_triangles(q[:, None, :], a[near], b[near], c[near])
        d = np.linalg.norm(best - q[:, None, :], axis=2)
        pick = np.argmin(d, axis=1)
        rows = np.arange(q.shape[0])
        out[start:start + 128] = best[rows, pick] + face_n[near[rows, pick]] * lift
    return out


def _closest_on_triangles(p, a, b, c):
    """Closest point on triangle abc to p, element-wise (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.sum(ab * ap, -1), np.sum(ac * ap, -1)
    bp = p - b
    d3, d4 = np.sum(ab * bp, -1), np.sum(ac * bp, -1)
    cp = p - c
    d5, d6 = np.sum(ab * cp, -1), np.sum(ac * cp, -1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    denom = np.where(np.abs(va + vb + vc) < 1e-18, 1e-18, va + vb + vc)
    v, w = vb / denom, vc / denom
    result = a + ab * v[..., None] + ac * w[..., None]  # inside the face
    # Edges and vertices, in the order the regions are tested.
    t_ab = np.clip(d1 / np.where(np.abs(d1 - d3) < 1e-18, 1e-18, d1 - d3), 0, 1)
    on_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    result = np.where(on_ab[..., None], a + ab * t_ab[..., None], result)
    t_ac = np.clip(d2 / np.where(np.abs(d2 - d6) < 1e-18, 1e-18, d2 - d6), 0, 1)
    on_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    result = np.where(on_ac[..., None], a + ac * t_ac[..., None], result)
    span_bc = (d4 - d3) + (d5 - d6)
    t_bc = np.clip((d4 - d3) / np.where(np.abs(span_bc) < 1e-18, 1e-18, span_bc), 0, 1)
    on_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    result = np.where(on_bc[..., None], b + (c - b) * t_bc[..., None], result)
    result = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, result)
    result = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, result)
    result = np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, result)
    return result


def _face_out(mesh: Mesh, outward: np.ndarray) -> None:
    """Wind each triangle so it faces the way the fabric under it faces."""
    tris = mesh.indices.reshape(-1, 3)
    p = mesh.positions.astype(np.float64)
    normal = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
    want = outward[tris].mean(axis=1)
    flip = np.sum(normal * want, axis=1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    mesh.indices = tris.reshape(-1).astype(np.uint32)
    mesh.compute_normals()


def _frame_at(vertex: int, ctx: _Ctx) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    origin = ctx.positions[vertex]
    normal = ctx.normals[vertex] / max(np.linalg.norm(ctx.normals[vertex]), 1e-9)
    up = np.array([0.0, 1.0, 0.0])
    up = up - normal * float(np.dot(up, normal))
    up /= max(np.linalg.norm(up), 1e-9)
    across = np.cross(up, normal)
    return origin, across, up, normal


def bow_local(size: float) -> Mesh:
    """A small satin bow in its own frame (x across, y up, z out): two loops, a knot, two tails."""
    from wardrobe.geometry.mesh import concatenate

    parts = []
    z = np.array([0.0, 0.0, 1.0])
    t = np.linspace(0.0, 2.0 * math.pi, 21)
    for sign in (-1.0, 1.0):
        # A loop out to one side and back, a little taller at its end, standing slightly off her.
        x = sign * 0.5 * size * (1 - np.cos(t)) / 2
        y = 0.22 * size * np.sin(t) * (0.6 + 0.4 * (1 - np.cos(t)) / 2)
        zz = 0.12 * size * (1 - np.cos(t)) / 2 + 0.06 * size
        loop = np.column_stack([x, y, zz])
        parts.append(ribbon(loop, np.repeat(z[None, :], loop.shape[0], axis=0), width=0.2 * size,
                            thickness=0.035 * size, name="bow-loop"))
        s = np.linspace(0.0, 1.0, 7)
        tail = np.column_stack([sign * 0.28 * size * s, -0.62 * size * s, 0.04 * size + 0.02 * size * s])
        parts.append(ribbon(tail, np.repeat(z[None, :], tail.shape[0], axis=0), width=0.15 * size,
                            thickness=0.035 * size, name="bow-tail"))
    knot_t = np.linspace(0.0, 2.0 * math.pi, 13)
    knot = np.column_stack([0.11 * size * np.cos(knot_t), 0.14 * size * np.sin(knot_t),
                            np.full(knot_t.size, 0.1 * size)])
    parts.append(ribbon(knot, np.repeat(z[None, :], knot.shape[0], axis=0), width=0.16 * size,
                        thickness=0.08 * size, name="bow-knot"))
    bow = concatenate(parts)
    bow.metadata = {"section": "bow", "sections": [("bow", 0, bow.triangle_count)]}
    return bow


def _place_bow(vertex: int, ctx: _Ctx, size: float, name: str) -> Mesh:
    from wardrobe.hosiery.hardware import place

    origin, across, up, normal = _frame_at(vertex, ctx)
    return place(bow_local(size), origin + normal * 0.001, across, up, normal, name)


def charm_local() -> Mesh:
    """A tiny gold drop on a jump ring: 3.6 mm ring, 7 mm teardrop below it, in its own frame."""
    from wardrobe.hosiery.hardware import _loop_tube, _mesh

    t = np.linspace(0.0, 2.0 * math.pi, 12, endpoint=False)
    ring = np.column_stack([0.0018 * np.cos(t), -0.0018 + 0.0018 * np.sin(t), np.zeros_like(t)])
    ring_p, ring_f = _loop_tube(ring, 0.00045, sides=4)
    # A teardrop outline, point up, filled as a fan and given a little thickness.
    s = np.linspace(0.0, 2.0 * math.pi, 18, endpoint=False)
    r = 0.0035 * (1 - 0.35 * np.sin(s))
    outline = np.column_stack([r * np.cos(s) * 0.85, -0.0075 + r * np.sin(s), np.zeros_like(s)])
    front = np.vstack([outline + [0, 0, 0.0006], [[0.0, -0.0075, 0.0009]]])
    back = np.vstack([outline - [0, 0, 0.0006], [[0.0, -0.0075, -0.0009]]])
    m = outline.shape[0]
    faces = []
    for i in range(m):
        j = (i + 1) % m
        faces += [(i, j, m), (m + 1 + j, m + 1 + i, 2 * m + 1)]
        faces += [(i, m + 1 + i, m + 1 + j), (i, m + 1 + j, j)]
    drop = (np.vstack([front, back]), np.array(faces, dtype=np.int64))
    return _mesh([(ring_p, ring_f), drop], "charm")


def _place_charm(vertex: int, ctx: _Ctx) -> Mesh:
    from wardrobe.hosiery.hardware import place

    origin, across, up, normal = _frame_at(vertex, ctx)
    return place(charm_local(), origin + normal * 0.0015, across, up, normal, "charm")


# ----------------------------------------------------------------------
# joining, and the component table
# ----------------------------------------------------------------------
def _section_triangles(mesh: Mesh, prefix: str) -> np.ndarray:
    out = [np.arange(first, first + n) for name, first, n in section_ranges(mesh) if name.startswith(prefix)]
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def _panel_triangles(mesh: Mesh) -> np.ndarray:
    out = [np.arange(first, first + n) for name, first, n in section_ranges(mesh) if name != "gusset"]
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def _assemble(mesh: Mesh, names: list[str], materials: list[str],
              pieces: list[tuple[str, str, Mesh]]) -> Mesh:
    from wardrobe.lingerie.blocks.bra import _join

    for _, _, piece in pieces:
        piece.metadata["placed"] = np.ones(piece.vertex_count, dtype=bool)
        if piece.uvs is None:
            piece.uvs = np.zeros((piece.vertex_count, 2), np.float32)
        if piece.normals is None:
            piece.compute_normals()
    gusset = mesh.metadata.get("gusset")
    joined = _join([mesh] + [p for _, _, p in pieces]) if pieces else mesh
    for component, material, piece in pieces:
        names += [component] * piece.triangle_count
        materials += [material] * piece.triangle_count
    table = sorted(set(names))
    # Per triangle, not per component: a panel and the elastic along its edge are one
    # component (bottom_front) of two materials.
    joined.metadata["components"] = {
        "names": table,
        "of": np.array([table.index(n) for n in names], dtype=np.int32),
        "material": np.array([MATERIALS.index(m) for m in materials], dtype=np.int8),
    }
    if gusset is not None:
        joined.metadata["gusset"] = gusset
    return joined


def component_table(mesh: Mesh) -> dict[str, dict]:
    """{component: {material, triangles}} for the node's extras (wardrobe.engines.native)."""
    record = mesh.metadata.get("components")
    if not record:
        return {}
    out = {}
    for i, name in enumerate(record["names"]):
        mine = record["material"][record["of"] == i]
        used = {MATERIALS[int(k)]: int(c) for k, c in zip(*np.unique(mine, return_counts=True), strict=True)}
        out[name] = {"materials": used, "triangles": int(mine.size)}
    return out


def material_masks(mesh: Mesh) -> dict[str, np.ndarray]:
    """One triangle mask per material, from the component table."""
    record = mesh.metadata.get("components")
    if not record:
        return {}
    per_triangle = np.asarray(record["material"])
    return {m: per_triangle == i for i, m in enumerate(MATERIALS) if np.any(per_triangle == i)}


__all__ = ["MATERIALS", "bow_local", "charm_local", "component_table", "embellish", "lace_band",
           "material_masks"]
