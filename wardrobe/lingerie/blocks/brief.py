"""The brief block: front and back panels, a gusset across the crotch, waist and leg elastics.

The haul brief was a band from low-rise to the leg opening with its bottom edge
lifted at the sides: an open tube, two openings, nothing under her. A brief is
three pieces. The **front and back panels** run from the waistband down to the
leg openings and meet at the side seams; the **gusset** is a strip, usually
lined, that crosses under the crotch from the front panel's lowest edge to the
back panel's. What is left open is exactly three edges: the waist and two legs.

**Drafted in her coordinates.** Heights are fractions of her crotch-to-waist
span (``BriefSpec``), so one spec grades across bodies: the centre-front
waistline at ``rise``, the back a little higher (``back_rise``), the side panel
``side_height`` tall. The leg line runs from the side down to each gusset
corner along a curve whose shape is the style: a front scoop, and a back that
covers the seat (``full``), less of it (``moderate``, ``cheeky``) or a strip
(``thong``). Every point is on her measured outline at its height plus the
fabric's clearance (``BodyFrame``), and the shell's conform pass then draws the
panels onto her surface.

**The gusset is placed, not conformed.** The fitter's passes push a shell out
from her vertical axis, which is right for a panel and meaningless for a strip
crossing under her: the axis runs through it. So its interior rows are marked
``placed`` (the shell leaves them) and are seated after the panels are fitted
(``wardrobe.lingerie.fit.after_shell``): between the two seams, which are the
panels' own edge vertices — shared, so the seams cannot open — and pushed out of
her posed surface to the clearance.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.lingerie.blocks.frame import BodyFrame
from wardrobe.lingerie.specs import BriefSpec

#: Across each gusset seam, and between the side seam and a gusset corner (per half).
GUSSET_COLUMNS = 6
LEG_HALF_COLUMNS = 7
#: Interior rows of the gusset, front seam to back seam.
GUSSET_ROWS = 9
#: Panel rows are at most this far apart.
ROW_STEP_M = 0.012
#: How far above her crotch landmark the gusset seams sit.
SEAM_ABOVE_CROTCH_M = 0.012
#: The leg line's curve toward the back gusset corner, by coverage: above 1 it stays
#: up over the seat and drops late, which is how far a back is cut away.
BACK_EASE = {"full": 0.7, "moderate": 1.4, "cheeky": 3.0, "thong": 7.0}
#: A thong's back is a strip this wide at the gusset.
THONG_BACK_M = 0.022


def _columns(phi_front: float, phi_back: float) -> np.ndarray:
    """Angles round her, starting and ending at her side seam at -90° (a UV seam there, as sewn)."""
    half = LEG_HALF_COLUMNS
    parts = [
        np.linspace(-math.pi / 2, -phi_front, half + 1)[:-1],
        np.linspace(-phi_front, phi_front, GUSSET_COLUMNS + 1),
        np.linspace(phi_front, math.pi - phi_back, 2 * half + 1)[1:-1],
        np.linspace(math.pi - phi_back, math.pi + phi_back, GUSSET_COLUMNS + 1),
        np.linspace(math.pi + phi_back, 1.5 * math.pi, half + 1)[1:],
    ]
    return np.concatenate(parts)


def build_brief(frame: BodyFrame, spec: BriefSpec, *, name: str = "brief") -> Mesh:
    marks, c = frame.marks, frame.clearance
    crotch, waist = marks.crotch_y, marks.waist_y
    span = max(waist - crotch, 0.08)
    front_waist = crotch + span * spec.rise
    back_waist = front_waist + span * spec.back_rise
    seam_y = crotch + SEAM_ABOVE_CROTCH_M
    side_waist = front_waist + (back_waist - front_waist) * 0.5
    side_bottom = max(side_waist - span * spec.side_height, seam_y + 0.015)

    a_front, _, _, _ = frame.outline(seam_y)
    front_half = spec.gusset_front_width_mm / 2000.0
    back_half = THONG_BACK_M / 2 if spec.back_coverage == "thong" else front_half * 1.2
    phi_front = math.asin(min(front_half / max(a_front + c, 1e-6), 0.9))
    phi_back = math.asin(min(back_half / max(a_front + c, 1e-6), 0.9))
    phis = _columns(phi_front, phi_back)
    count = phis.size

    def waistline(phi: np.ndarray) -> np.ndarray:
        return front_waist + (back_waist - front_waist) * (1 - np.cos(phi)) / 2

    def leg_line(phi: np.ndarray) -> np.ndarray:
        wrapped = np.abs(np.angle(np.exp(1j * phi)))  # 0 at her front, pi at her back
        y = np.full(phi.shape, side_bottom)
        front = wrapped <= math.pi / 2
        t_front = np.clip((math.pi / 2 - wrapped) / max(math.pi / 2 - phi_front, 1e-6), 0.0, 1.0)
        t_back = np.clip((wrapped - math.pi / 2) / max(math.pi / 2 - phi_back, 1e-6), 0.0, 1.0)
        y_front = side_bottom + (seam_y - side_bottom) * t_front ** (1.0 + 2.5 * spec.front_scoop)
        y_back = side_bottom + (seam_y - side_bottom) * t_back ** BACK_EASE[spec.back_coverage]
        return np.where(front, y_front, np.where(wrapped > math.pi / 2, y_back, y))

    top, bottom = waistline(phis), leg_line(phis)
    rows = max(int(math.ceil(float((top - bottom).max()) / ROW_STEP_M)), 4)

    positions = np.empty(((rows + 1) * count, 3))
    uvs = np.empty(((rows + 1) * count, 2))
    for k in range(rows + 1):
        ys = top + (bottom - top) * k / rows
        ring = frame.point(phis, ys)
        positions[k * count:(k + 1) * count] = ring
        along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(ring, axis=0), axis=1))])
        uvs[k * count:(k + 1) * count] = np.column_stack([along, top - ys])

    def vid(k: int, j: int) -> int:
        return k * count + j

    front_cols = list(range(LEG_HALF_COLUMNS, LEG_HALF_COLUMNS + GUSSET_COLUMNS + 1))
    back_start = LEG_HALF_COLUMNS + GUSSET_COLUMNS + 2 * LEG_HALF_COLUMNS
    back_cols = list(range(back_start, back_start + GUSSET_COLUMNS + 1))
    gusset_cols = set(front_cols[:-1]) | set(back_cols[:-1])

    # Gusset: rows from the front seam (the front panel's lowest vertices, left to right)
    # to the back seam (the back panel's, reversed so they also run left to right).
    front_seam = [vid(rows, j) for j in front_cols]
    back_seam = [vid(rows, j) for j in back_cols[::-1]]
    if frame.forward < 0:  # facing -Z, increasing phi runs toward -x
        front_seam, back_seam = front_seam[::-1], back_seam[::-1]
    gusset_rows, gusset_positions, gusset_uvs = [], [], []
    base = positions.shape[0]
    for r in range(1, GUSSET_ROWS + 1):
        t = r / (GUSSET_ROWS + 1)
        row = []
        for i in range(GUSSET_COLUMNS + 1):
            p = gusset_point(positions[front_seam[i]], positions[back_seam[i]], t, i, frame, spec)
            row.append(base + len(gusset_positions))
            gusset_positions.append(p)
            v = float(uvs[front_seam[0], 1]) + t * spec.gusset_length_mm / 1000
            gusset_uvs.append([p[0] - marks.centre_x, v])
        gusset_rows.append(row)
    positions = np.vstack([positions, np.array(gusset_positions)])
    uvs = np.vstack([uvs, np.array(gusset_uvs)])
    grid = [front_seam, *gusset_rows, back_seam]

    faces: dict[str, list[tuple[int, int, int]]] = {
        "elastic-brief-waist": [], name: [], "elastic-brief-leg": [], "gusset": []}
    for k in range(rows):
        for j in range(count - 1):
            a, b, cc, d = vid(k, j), vid(k, j + 1), vid(k + 1, j + 1), vid(k + 1, j)
            if k == 0:
                section = "elastic-brief-waist"
            elif k == rows - 1 and j not in gusset_cols:
                section = "elastic-brief-leg"
            else:
                section = name
            faces[section] += [(a, cc, b), (a, d, cc)]
    for r in range(len(grid) - 1):
        for i in range(GUSSET_COLUMNS):
            a, b, cc, d = grid[r][i], grid[r][i + 1], grid[r + 1][i + 1], grid[r + 1][i]
            edge = i in (0, GUSSET_COLUMNS - 1)
            faces["elastic-brief-leg" if edge else "gusset"] += [(a, b, cc), (a, cc, d)]

    order = ["elastic-brief-waist", name, "elastic-brief-leg", "gusset"]
    indices, sections, start = [], [], 0
    for section in order:
        tris = faces[section]
        indices += tris
        sections.append((section, start, len(tris)))
        start += len(tris)

    placed = np.zeros(positions.shape[0], dtype=bool)
    placed[base:] = True
    mesh = Mesh(positions=positions.astype(np.float32),
                indices=np.array(indices, dtype=np.uint32).reshape(-1),
                uvs=uvs.astype(np.float32), metadata={"section": name})
    _orient_outward(mesh, frame)
    mesh.compute_normals()
    _weld_seam_normals(mesh, [vid(k, 0) for k in range(rows + 1)],
                       [vid(k, count - 1) for k in range(rows + 1)])
    right_side = LEG_HALF_COLUMNS + GUSSET_COLUMNS + LEG_HALF_COLUMNS
    # Each leg opening: the panels' lower edge from one gusset corner round her side to
    # the other (the -x one crosses the side seam's two copies), then the gusset's edge.
    negative_leg = ([vid(rows, j) for j in range(back_cols[-1], count)]
                    + [vid(rows, j) for j in range(0, front_cols[0] + 1)])
    positive_leg = [vid(rows, j) for j in range(front_cols[-1], back_cols[0] + 1)]
    mesh.metadata.update({
        "sections": sections,
        "placed": placed,
        "lingerieBrief": {
            "rows": rows, "columns": count,
            "waist": [vid(0, j) for j in range(count)],
            "legOpenings": {"negativeX": negative_leg, "positiveX": positive_leg},
            "gusset": [list(map(int, row)) for row in grid],
            "sideSeam": {"a": [vid(k, 0) for k in range(rows + 1)],
                         "b": [vid(k, count - 1) for k in range(rows + 1)]},
            "sideAnchors": {"negativeX": vid(0, 0), "positiveX": vid(0, right_side)},
            "centreFront": vid(0, front_cols[len(front_cols) // 2]),
            "centreBack": vid(0, back_cols[len(back_cols) // 2]),
            "spec": {"rise": spec.rise, "backRise": spec.back_rise, "sideHeight": spec.side_height,
                     "backCoverage": spec.back_coverage, "gussetWidthMm": spec.gusset_width_mm,
                     "gussetFrontWidthMm": spec.gusset_front_width_mm},
            "heights": {"frontWaist": front_waist, "backWaist": back_waist, "sideBottom": side_bottom,
                        "seam": seam_y, "crotch": crotch, "waist": waist},
        },
    })
    return mesh


def gusset_point(front: np.ndarray, back: np.ndarray, t: float, i: int, frame: BodyFrame,
                 spec: BriefSpec) -> np.ndarray:
    """A first placement across the crotch: a curve from seam to seam through a point under her.

    Only a start — ``wardrobe.lingerie.fit.after_shell`` seats the gusset on her
    posed surface once the panels (and so its seams) are fitted.
    """
    marks, c = frame.marks, frame.clearance
    across = (i / GUSSET_COLUMNS - 0.5) * spec.gusset_width_mm / 1000.0
    _, _, cx, cz = frame.outline(marks.crotch_y)
    middle = np.array([marks.centre_x + across, marks.crotch_y - c - 0.004, cz])
    control = 2 * middle - (front + back) / 2
    return (1 - t) ** 2 * front + 2 * (1 - t) * t * control + t ** 2 * back


def _orient_outward(mesh: Mesh, frame: BodyFrame) -> None:
    """Wind every triangle so its normal points away from her: the panels' and the gusset's alike."""
    tris = mesh.indices.reshape(-1, 3)
    p = mesh.positions.astype(np.float64)
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    normal = np.cross(b - a, c - a)
    centre = (a + b + c) / 3
    axis = np.column_stack([np.full(len(tris), frame.marks.centre_x), centre[:, 1], np.zeros(len(tris))])
    _, _, _, cz = frame.outline(frame.marks.full_hip_y)
    axis[:, 2] = cz
    outward = centre - axis
    # Under the crotch "away from her" is down.
    low = centre[:, 1] < frame.marks.crotch_y + SEAM_ABOVE_CROTCH_M * 0.5
    outward[low] = [0.0, -1.0, 0.0]
    flip = np.sum(normal * outward, axis=1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    mesh.indices = tris.reshape(-1).astype(np.uint32)


def _weld_seam_normals(mesh: Mesh, a: list[int], b: list[int]) -> None:
    """The side seam's two copies of each vertex share one normal: no crease shading down her side."""
    n = mesh.normals.astype(np.float64)
    avg = n[a] + n[b]
    avg /= np.maximum(np.linalg.norm(avg, axis=1, keepdims=True), 1e-9)
    n[a] = avg
    n[b] = avg
    mesh.normals = n.astype(np.float32)


__all__ = ["BACK_EASE", "GUSSET_COLUMNS", "GUSSET_ROWS", "build_brief", "gusset_point"]
