"""The bra block: cups on her bust points, a gore on her sternum, a band under the fold, straps to the cups.

The haul bra was one lofted band from underbust to bust top with its top edge
re-cut into peaks at a fixed angle: it bridged straight across between her
breasts, its "cups" were wherever that angle fell, and its straps were cords
from wherever the top edge was. A bra is pieces placed on landmarks:

* the **underband** runs level round her at the fold under her bust
  (``BodyLandmarks.underbust_y``), ``underband_width_mm`` deep, elastic along
  its lower edge; at her back it rises into the **wings**, ``wing_height_mm``,
  which carry the closure and the back strap anchors;
* the **gore** is the band's centre panel between the cups, ``gore_height_mm``
  tall, lying on her sternum — the depth map's own surface at her midline, which
  between two bust points is the dip, not a bridge;
* each **cup** is a patch on her front surface around her bust point: its lower
  edge *is* the band's top edge (the same vertices), its inner edge rises from
  the gore, its outer edge from the side, and its top is a peak (triangle) or a
  neckline (balconette, plunge, full). Above the bust point the cup does not
  cling to her upper chest: fabric under a strap's pull runs straight from the
  bust point to where the strap is sewn, so it bridges there and follows her
  only where she is proud of that line;
* each **strap** is an L2 ribbon from the anchor the cup publishes (its peak, or
  the neckline's strap point) to the wing's top at her back.

The band's front half and the cups are placed on her measured front
(``upperBody``) and marked ``placed``; the shell's radial passes fit the wings.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate
from wardrobe.lingerie.blocks.frame import BodyFrame
from wardrobe.lingerie.contract import Anchor
from wardrobe.lingerie.specs import BraSpec, StrapBlock
from wardrobe.lingerie.straps import build_ribbon_strap, surface_normal

#: Columns across each cup, rows up it, and band rows.
CUP_COLUMNS = 10
CUP_ROWS = 10
BAND_ROWS = 3
#: Columns round the back half of the band (between the two cups' outer edges, behind).
BACK_COLUMNS = 24
#: Columns across the gore.
GORE_COLUMNS = 4
#: How far above her bust point a neckline passes, at least, by style.
COVER_MIN_M = 0.016
COVER = {"full": 0.03}
#: A triangle cup's top is not a single point, which would make slivers: it is this wide.
PEAK_WIDTH_M = 0.008

#: Per style: the neckline's outer top as a fraction of (bust point → fold) above the bust
#: point, and where along the neckline (inner 0 → outer 1) the strap is sewn. The inner top
#: is the gore's: a neckline starts where the gore ends (a triangle has no neckline, a peak).
NECKLINES = {
    "triangle": (None, 0.5),
    "balconette": (0.45, 0.75),
    "plunge": (0.65, 0.85),
    "full": (0.9, 0.6),
}


def _front(frame: BodyFrame, x: float, y: float, lift: float) -> np.ndarray | None:
    return frame.surface(x, y, "front", lift)


def build_bra(frame: BodyFrame, spec: BraSpec, straps: StrapBlock, *, name: str = "bra") -> Mesh:
    marks, c = frame.marks, frame.clearance
    cx = marks.centre_x
    fold = min(marks.underbust_y.values())
    apex = {side: np.asarray(p, dtype=np.float64) for side, p in marks.bust_points.items()}
    depth = max(float(np.mean([p[1] for p in apex.values()])) - fold, 0.03)
    band_bottom = fold - spec.underband_width_mm / 1000.0
    gore_top = band_bottom + max(spec.gore_height_mm, spec.underband_width_mm) / 1000.0
    wing_top = band_bottom + spec.wing_height_mm / 1000.0
    lift = c + spec.cup_ease_mm / 1000.0

    # Cup outline in body space, per side (sign +1: +x).
    cups = {}
    for side, point in apex.items():
        sign = 1.0 if point[0] >= cx else -1.0
        reach = abs(point[0] - cx)
        x_in = cx + sign * max(spec.gore_width_mm / 2000.0, reach * (1.0 - spec.cup_inner))
        # Not round her side: past 85% of her half-width the front depth map is a wall.
        half, _, _, _ = frame.outline(float(point[1]))
        x_out = cx + sign * min(reach * (1.0 + spec.cup_outer), half * 0.85)
        outer_top, strap_at = NECKLINES[spec.style]
        if outer_top is None:  # triangle: the top is a short peak over the bust point
            peak_y = point[1] + depth * spec.cup_height
            top_in = (point[0] - sign * PEAK_WIDTH_M / 2, peak_y)
            top_out = (point[0] + sign * PEAK_WIDTH_M / 2, peak_y)
        else:
            top_in = (x_in, gore_top)
            # The outer edge leans in toward the strap, as a cup's does: a corner out at
            # x_out's height would stand where her front turns into her side.
            top_out = (x_out - sign * 0.3 * abs(x_out - point[0]),
                       point[1] + depth * outer_top * spec.cup_height)
        bow = 0.0 if outer_top is None else depth * 0.18
        if outer_top is not None:
            # Whatever the style, the cup covers her bust point: where the neckline
            # crosses above it, it is at least COVER above it, the curve raised if not.
            s_apex = float(np.clip((point[0] - top_in[0]) / (top_out[0] - top_in[0]), 0.05, 0.95))
            line = top_in[1] + (top_out[1] - top_in[1]) * s_apex + bow * s_apex * (1 - s_apex)
            need = point[1] + COVER.get(spec.style, COVER_MIN_M)
            if line < need:
                bow += (need - line) / (s_apex * (1 - s_apex))
        cups[side] = {"sign": sign, "apex": point, "x_in": x_in, "x_out": x_out, "top_in": top_in,
                      "top_out": top_out, "strap_at": strap_at, "bow": bow}

    # ---- the band: one ring, front half on her depth map, back half fitted radially.
    # Columns (x at the front, then angle round her back), from her -x cup's outer edge.
    neg, pos = (cups[s] for s in sorted(cups, key=lambda s: cups[s]["sign"]))
    front_x = np.concatenate([
        np.linspace(neg["x_out"], neg["x_in"], CUP_COLUMNS + 1),
        np.linspace(neg["x_in"], pos["x_in"], GORE_COLUMNS + 1)[1:-1],
        np.linspace(pos["x_in"], pos["x_out"], CUP_COLUMNS + 1),
    ])
    front_count = front_x.size
    a_band, _b, _cx, _cz = frame.outline(fold)
    phi_side = math.asin(min(abs(pos["x_out"] - cx) / max(a_band + c, 1e-6), 0.98))
    back_phi = np.linspace(phi_side, 2 * math.pi - phi_side, BACK_COLUMNS + 1)[1:-1]
    back_count = back_phi.size

    inner = min(abs(pos["x_in"] - cx), abs(neg["x_in"] - cx))
    ramp = 0.3 * min(abs(pos["x_out"] - pos["x_in"]), abs(neg["x_out"] - neg["x_in"]))

    def top_front(x: float) -> float:
        """The band's top edge across her front: the gore, easing down to the fold under the cups."""
        t = np.clip((abs(x - cx) - inner) / max(ramp, 1e-6), 0.0, 1.0)
        return gore_top + (fold - gore_top) * float(0.5 - 0.5 * np.cos(np.pi * t))

    def top_back(phi: float) -> float:
        # From the fold at the cups' outer edges up to the wing height behind her.
        round_her = abs(np.angle(np.exp(1j * phi)))
        t = np.clip((round_her - phi_side) / max(math.pi / 2 - phi_side, 1e-6), 0.0, 1.0)
        return fold + (wing_top - fold) * float(t * t * (3 - 2 * t))

    positions: list[np.ndarray] = []
    band_index = np.zeros((BAND_ROWS + 1, front_count + back_count + 1), dtype=np.int64)
    for k in range(BAND_ROWS + 1):
        for j, x in enumerate(front_x):
            y = band_bottom + (top_front(x) - band_bottom) * k / BAND_ROWS
            p = _front(frame, float(x), y, c)
            if p is None:
                p = frame.point(np.array([math.asin(np.clip((x - cx) / (a_band + c), -1, 1))]), y)[0]
            band_index[k, j] = len(positions)
            positions.append(p)
        for j, phi in enumerate(back_phi):
            y = band_bottom + (top_back(phi) - band_bottom) * k / BAND_ROWS
            band_index[k, front_count + j] = len(positions)
            positions.append(frame.point(np.array([phi]), y)[0])
        band_index[k, -1] = band_index[k, 0]  # closed ring
    front_placed = {int(v) for v in band_index[:, :front_count].reshape(-1)}

    # ---- the cups: their lower row is the band's top row under them.
    cup_rows: dict[str, list[list[int]]] = {}
    anchors: dict[str, Anchor] = {}
    for side, cup in cups.items():
        span = (range(0, CUP_COLUMNS + 1) if cup is neg else
                range(front_count - CUP_COLUMNS - 1, front_count))
        bottom = [int(band_index[BAND_ROWS, j]) for j in span]
        if cup["sign"] < 0:
            bottom = bottom[::-1]  # inner (gore) to outer
        rows = [bottom]
        start = np.array([positions[v] for v in bottom])
        # The bust point's own row: the cup bridges straight from here to its top.
        apex_row = None
        for r in range(1, CUP_ROWS + 1):
            t = r / CUP_ROWS
            row = []
            for i in range(CUP_COLUMNS + 1):
                s = i / CUP_COLUMNS
                x0, y0 = start[i, 0], start[i, 1]
                tx = cup["top_in"][0] + (cup["top_out"][0] - cup["top_in"][0]) * s
                # A neckline is a curve, a little fuller in the middle, never a ruled line.
                ty = cup["top_in"][1] + (cup["top_out"][1] - cup["top_in"][1]) * s + cup["bow"] * s * (1 - s)
                x, y = x0 + (tx - x0) * t, y0 + (ty - y0) * t
                p = _front(frame, float(x), float(y), lift)
                if p is None:
                    p = np.array([x, y, positions[bottom[i]][2]])
                row.append(p)
            row = np.array(row)
            if apex_row is None and float(np.mean(row[:, 1])) >= cup["apex"][1]:
                apex_row = (r, row.copy())
            rows.append(row)
        # Bridge above the bust point: straight from the bust-point row to the top, never inside her.
        if apex_row is not None:
            r0, base = apex_row
            top = rows[-1]
            for r in range(r0 + 1, CUP_ROWS):
                t = (r - r0) / (CUP_ROWS - r0)
                line = base + (top - base) * t
                surface = rows[r]
                forward = frame.forward
                proud = line[:, 2] * forward > surface[:, 2] * forward
                rows[r][:, 2] = np.where(proud, line[:, 2], surface[:, 2])
        indexed = [bottom]
        for row in rows[1:]:
            ids = []
            for p in row:
                ids.append(len(positions))
                positions.append(np.asarray(p, dtype=np.float64))
            indexed.append(ids)
        cup_rows[side] = indexed
        # The strap is sewn at the neckline's strap point (a triangle's peak).
        top_ids = indexed[-1]
        at = top_ids[int(round(cup["strap_at"] * CUP_COLUMNS))]
        anchor_p = np.asarray(positions[at], dtype=np.float64)
        n = surface_normal(frame.params, float(anchor_p[0]), float(anchor_p[1]), "front")
        if n is None:
            n = np.array([0.0, 0.0, frame.forward])
        up = np.array([0.0, 1.0, 0.0])
        tangent = up - n * float(np.dot(up, n))
        anchors[side] = Anchor(name="cup-strap", side=side, position=anchor_p, normal=n,
                               tangent=tangent / max(np.linalg.norm(tangent), 1e-9), source="cup", vertex=at)

    positions_arr = np.array(positions)
    faces: dict[str, list[tuple[int, int, int]]] = {"elastic-bra-band": [], "bra-band": [], "bra-cups": []}
    columns = band_index.shape[1]
    for k in range(BAND_ROWS):
        for j in range(columns - 1):
            a, b = band_index[k, j], band_index[k, j + 1]
            cc, d = band_index[k + 1, j + 1], band_index[k + 1, j]
            faces["elastic-bra-band" if k == 0 else "bra-band"] += [(a, b, cc), (a, cc, d)]
    for rows in cup_rows.values():
        for r in range(len(rows) - 1):
            for i in range(CUP_COLUMNS):
                a, b, cc, d = rows[r][i], rows[r][i + 1], rows[r + 1][i + 1], rows[r + 1][i]
                faces["bra-cups"] += [(a, b, cc), (a, cc, d)]
    order = ["elastic-bra-band", "bra-band", "bra-cups"]
    indices, sections, first = [], [], 0
    for section in order:
        indices += faces[section]
        sections.append((section, first, len(faces[section])))
        first += len(faces[section])
    body = Mesh(positions=positions_arr.astype(np.float32),
                indices=np.array(indices, dtype=np.uint32).reshape(-1),
                uvs=_uvs(positions_arr, cx, band_bottom), metadata={"section": name})
    _orient(body, frame)
    body.compute_normals()
    placed = np.zeros(body.vertex_count, dtype=bool)
    placed[list(front_placed)] = True
    for rows in cup_rows.values():
        placed[[v for row in rows for v in row]] = True
    body.metadata.update({"sections": sections, "placed": placed})

    # ---- straps, from the cups' anchors to the wings' tops at her back.
    pieces = [body]
    fitted = {}
    if straps.style == "shoulder":
        for side, cup in cups.items():
            front = anchors[side]
            back_x = cx + cup["sign"] * abs(front.position[0] - cx) * 0.9
            back_p = frame.surface(back_x, wing_top - 0.004, "back", c)
            back_n = surface_normal(frame.params, back_x, wing_top - 0.004, "back")
            if back_p is None or back_n is None:
                continue
            back = Anchor(name="wing-strap", side=side, position=back_p, normal=back_n,
                          tangent=np.array([0.0, 1.0, 0.0]), source="band")
            built = build_ribbon_strap(frame.params, front, back, spec=straps.strap_spec(), name="strap")
            if built is None:
                continue
            mesh, strap = built
            mesh.metadata["placed"] = np.ones(mesh.vertex_count, dtype=bool)
            pieces.append(mesh)
            fitted[side] = strap.to_dict()
    out = _join(pieces)
    out.metadata["lingerieBra"] = {
        "style": spec.style,
        "fold": fold, "bandBottom": band_bottom, "goreTop": gore_top, "wingTop": wing_top,
        "cups": {side: {"apex": [float(v) for v in cup["apex"]], "xIn": cup["x_in"], "xOut": cup["x_out"],
                        "top": [list(cup["top_in"]), list(cup["top_out"])],
                        "rows": cup_rows[side]} for side, cup in cups.items()},
        "bandRows": band_index.tolist(),
        "frontColumns": front_count,
        "anchors": {side: a.to_dict() for side, a in anchors.items()},
        "straps": fitted,
    }
    return out


def _uvs(positions: np.ndarray, cx: float, bottom: float) -> np.ndarray:
    """Metres of fabric, near enough: across her and up from the band's lower edge."""
    return np.column_stack([positions[:, 0] - cx, positions[:, 1] - bottom]).astype(np.float32)


def _orient(mesh: Mesh, frame: BodyFrame) -> None:
    tris = mesh.indices.reshape(-1, 3)
    p = mesh.positions.astype(np.float64)
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    normal = np.cross(b - a, c - a)
    centre = (a + b + c) / 3
    _, _, cx, cz = frame.outline(float(np.mean(centre[:, 1])))
    outward = centre - np.column_stack([np.full(len(tris), cx), centre[:, 1], np.full(len(tris), cz)])
    flip = np.sum(normal * outward, axis=1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    mesh.indices = tris.reshape(-1).astype(np.uint32)


def _join(pieces: list[Mesh]) -> Mesh:
    """Concatenate, keeping each piece's sections and placed mask (offset) — concatenate() keeps neither."""
    sections, placed, offset_t = [], [], 0
    for piece in pieces:
        own = piece.metadata.get("sections") or [
            (piece.metadata.get("section", "piece"), 0, piece.triangle_count)]
        sections += [(n, f + offset_t, c) for n, f, c in own]
        offset_t += piece.triangle_count
        mask = piece.metadata.get("placed")
        placed.append(mask if mask is not None else np.zeros(piece.vertex_count, dtype=bool))
    out = concatenate(pieces) if len(pieces) > 1 else pieces[0]
    out.metadata = dict(pieces[0].metadata)
    out.metadata["sections"] = sections
    out.metadata["placed"] = np.concatenate(placed)
    return out


__all__ = ["COVER", "COVER_MIN_M", "NECKLINES", "build_bra"]
