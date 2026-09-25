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
from dataclasses import asdict

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.lingerie.blocks.frame import BodyFrame
from wardrobe.lingerie.specs import BriefSpec

#: Across each gusset seam, and between the side seam and a gusset corner (per half).
GUSSET_COLUMNS = 6
LEG_HALF_COLUMNS = 12
#: Interior rows of the gusset, front seam to back seam.
GUSSET_ROWS = 9
#: Panel rows are at most this far apart.
ROW_STEP_M = 0.012
#: How far above her crotch landmark the gusset seams sit.
SEAM_ABOVE_CROTCH_M = 0.012
#: Side and back-centre widths are drafted for a 1.68 m base body and graded by height.
BASE_HEIGHT_M = 1.68
#: How deep a full V (``*_v_depth`` 1.0) dips the waistline, as a fraction of the panel's
#: height at that centre, and over what angle either side of the centre it runs.
V_DIP = 0.35
V_SPAN = math.pi / 3
#: A string side is never less than this, whatever the spec: it is an elastic.
MIN_SIDE_M = 0.003
#: The leg line's curve exponent is solved within these bounds.
EASE_MIN, EASE_MAX = 0.05, 80.0


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
    grade = frame.params.height / BASE_HEIGHT_M
    front_waist = crotch + span * spec.rise_fraction
    back_waist = front_waist + span * spec.back_rise
    seam_y = crotch + SEAM_ABOVE_CROTCH_M
    side_waist = front_waist + (back_waist - front_waist) * 0.5
    # The side: from the leg cut if given, else its width, else the legacy fraction.
    if spec.leg_cut_height is not None:
        side_bottom = crotch + span * spec.leg_cut_height
    elif spec.side_width_mm is not None:
        side_bottom = side_waist - spec.side_width_mm / 1000.0 * grade
    else:
        side_bottom = side_waist - span * (0.42 if spec.side_height is None else spec.side_height)
    side_bottom = float(np.clip(side_bottom, seam_y + 0.004, side_waist - MIN_SIDE_M))

    a_front, _, _, _ = frame.outline(seam_y)
    front_half = spec.gusset_front_width_mm / 2000.0
    back_half = (spec.back_center_width_mm / 2000.0 * grade if spec.back_center_width_mm is not None
                 else front_half * 1.2)
    phi_front = math.asin(min(front_half / max(a_front + c, 1e-6), 0.9))
    phi_back = math.asin(min(max(back_half, 0.0015) / max(a_front + c, 1e-6), 0.9))
    phis = _columns(phi_front, phi_back)
    count = phis.size

    def waistline(phi: np.ndarray) -> np.ndarray:
        wrapped = np.abs(np.angle(np.exp(1j * phi)))
        base = front_waist + (back_waist - front_waist) * (1 - np.cos(phi)) / 2
        # V-shaping: the waistline dips toward a centre, straight-sided, as a V-string's
        # waist meets its string or a Brazilian's back panel narrows.
        front_v = np.clip(1.0 - wrapped / V_SPAN, 0.0, None)
        back_v = np.clip(1.0 - (math.pi - wrapped) / V_SPAN, 0.0, None)
        dip = (spec.front_v_depth * V_DIP * (front_waist - seam_y) * front_v
               + spec.back_v_depth * V_DIP * (back_waist - seam_y) * back_v)
        return base - dip

    def leg_line(phi: np.ndarray, p_front: float, p_back: float) -> np.ndarray:
        wrapped = np.abs(np.angle(np.exp(1j * phi)))  # 0 at her front, pi at her back
        t_front = np.clip((math.pi / 2 - wrapped) / max(math.pi / 2 - phi_front, 1e-6), 0.0, 1.0)
        t_back = np.clip((wrapped - math.pi / 2) / max(math.pi / 2 - phi_back, 1e-6), 0.0, 1.0)
        y_front = side_bottom + (seam_y - side_bottom) * t_front ** p_front
        y_back = side_bottom + (seam_y - side_bottom) * t_back ** p_back
        return np.where(wrapped <= math.pi / 2, y_front, y_back)

    def coverage(half: str, p: float) -> float:
        """How much of the panel's height (waistline → gusset seam) is covered, averaged round that half."""
        grid = np.linspace(0.0, math.pi / 2, 181) + (0.0 if half == "front" else math.pi / 2)
        top = waistline(grid)
        low = leg_line(grid, p, p)
        return float(np.mean(np.clip((top - low) / np.maximum(top - seam_y, 1e-6), 0.0, 1.0)))

    def solve(half: str, target: float) -> float:
        """The leg line's curve exponent that makes this half's coverage the spec's (bisection, in log)."""
        lo, hi = math.log(EASE_MIN), math.log(EASE_MAX)
        if coverage(half, EASE_MIN) <= target:
            return EASE_MIN
        if coverage(half, EASE_MAX) >= target:
            return EASE_MAX
        for _ in range(48):
            mid = (lo + hi) / 2
            if coverage(half, math.exp(mid)) > target:
                lo = mid
            else:
                hi = mid
        return math.exp((lo + hi) / 2)

    p_front = solve("front", spec.front_fraction)
    p_back = solve("back", spec.back_fraction)
    top, bottom = waistline(phis), leg_line(phis, p_front, p_back)
    measures = {
        "frontCoverage": coverage("front", p_front), "backCoverage": coverage("back", p_back),
        "sideWidthMm": (side_waist - side_bottom) * 1000.0,
        "legCutHeight": (side_bottom - crotch) / span,
        "backCenterWidthMm": 2 * max(back_half, 0.0015) * 1000.0,
        "frontVDepth": float(front_waist - waistline(np.array([0.0]))[0]) / max(front_waist - seam_y, 1e-6),
        "backVDepth": float(back_waist - waistline(np.array([math.pi]))[0]) / max(back_waist - seam_y, 1e-6),
        "rise": spec.rise_fraction, "legEase": {"front": p_front, "back": p_back},
    }

    rows = max(int(math.ceil(float((top - bottom).max()) / ROW_STEP_M)), 4)

    positions = np.empty(((rows + 1) * count, 3))
    uvs = np.empty(((rows + 1) * count, 2))
    for k in range(rows + 1):
        ys = top + (bottom - top) * k / rows
        ring = frame.point(phis, ys)
        positions[k * count:(k + 1) * count] = ring
        along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(ring, axis=0), axis=1))])
        uvs[k * count:(k + 1) * count] = np.column_stack([along, top - ys])

    # The side seam's two copies are one point, exactly: computed twice, float rounding
    # left some a hair apart and the seam read as slits.
    positions[count - 1::count] = positions[0::count]

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

    extended = spec.leg_extension_mm > 0.0
    faces: dict[str, list[tuple[int, int, int]]] = {
        "elastic-brief-waist": [], name: [], "elastic-brief-leg": [], "gusset": []}
    for k in range(rows):
        for j in range(count - 1):
            a, b, cc, d = vid(k, j), vid(k, j + 1), vid(k + 1, j + 1), vid(k + 1, j)
            if k == 0:
                section = "elastic-brief-waist"
            elif k == rows - 1 and j not in gusset_cols and not extended:
                section = "elastic-brief-leg"
            else:
                section = name
            faces[section] += [(a, cc, b), (a, d, cc)]
    for r in range(len(grid) - 1):
        for i in range(GUSSET_COLUMNS):
            a, b, cc, d = grid[r][i], grid[r][i + 1], grid[r + 1][i + 1], grid[r + 1][i]
            edge = i in (0, GUSSET_COLUMNS - 1) and not extended
            faces["elastic-brief-leg" if edge else "gusset"] += [(a, b, cc), (a, cc, d)]

    # Each leg opening as a closed loop: the panels' lower edge from one gusset corner round
    # her side to the other (the -x one crosses the side seam once), then the gusset's edge.
    negative_leg = ([vid(rows, j) for j in range(back_cols[-1], count - 1)]
                    + [vid(rows, j) for j in range(0, front_cols[0] + 1)])
    positive_leg = [vid(rows, j) for j in range(front_cols[-1], back_cols[0] + 1)]
    column = {"negativeX": 0, "positiveX": GUSSET_COLUMNS}
    if frame.forward < 0:
        column = {"negativeX": GUSSET_COLUMNS, "positiveX": 0}
    loops = {
        "negativeX": negative_leg + [grid[r][column["negativeX"]] for r in range(1, len(grid) - 1)],
        "positiveX": positive_leg + [grid[r][column["positiveX"]] for r in range(len(grid) - 2, 0, -1)],
    }
    body_triangles = sum(len(t) for t in faces.values())
    extension_faces: list[tuple[int, int, int]] = []
    extension_elastic: list[tuple[int, int, int]] = []
    extension = None
    if extended:
        positions, uvs, extension_faces, extension_elastic, extension = _extend_legs(
            frame, positions, uvs, loops, spec.leg_extension_mm / 1000.0 * grade)

    order = ["elastic-brief-waist", name, "elastic-brief-leg", "gusset"]
    indices, sections, start = [], [], 0
    for section in order:
        tris = faces[section]
        indices += tris
        sections.append((section, start, len(tris)))
        start += len(tris)
    if extended:
        for section, tris in ((f"{name}-leg", extension_faces), ("elastic-brief-leg", extension_elastic)):
            indices += tris
            sections.append((section, start, len(tris)))
            start += len(tris)

    placed = np.zeros(positions.shape[0], dtype=bool)
    placed[base:] = True
    mesh = Mesh(positions=positions.astype(np.float32),
                indices=np.array(indices, dtype=np.uint32).reshape(-1),
                uvs=uvs.astype(np.float32), metadata={"section": name})
    _orient_outward(mesh, frame, limit=body_triangles)
    mesh.compute_normals()
    _weld_seam_normals(mesh, [vid(k, 0) for k in range(rows + 1)],
                       [vid(k, count - 1) for k in range(rows + 1)])
    right_side = LEG_HALF_COLUMNS + GUSSET_COLUMNS + LEG_HALF_COLUMNS
    mesh.metadata.update({
        "sections": sections,
        "placed": placed,
        "lingerieBrief": {
            "rows": rows, "columns": count,
            "waist": [vid(0, j) for j in range(count)],
            "legOpenings": {"negativeX": loops["negativeX"], "positiveX": loops["positiveX"]},
            "legExtension": extension,
            "gusset": [list(map(int, row)) for row in grid],
            "sideSeam": {"a": [vid(k, 0) for k in range(rows + 1)],
                         "b": [vid(k, count - 1) for k in range(rows + 1)]},
            "sideAnchors": {"negativeX": vid(0, 0), "positiveX": vid(0, right_side)},
            "centreFront": vid(0, front_cols[len(front_cols) // 2]),
            "centreBack": vid(0, back_cols[len(back_cols) // 2]),
            "spec": {k: v for k, v in asdict(spec).items() if v is not None},
            # What the pattern measures, from its own lines: what the style tests hold.
            "measures": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in measures.items()},
            "heights": {"frontWaist": front_waist, "backWaist": back_waist, "sideBottom": side_bottom,
                        "seam": seam_y, "crotch": crotch, "waist": waist},
        },
    })
    if spec.side_type == "tie":
        mesh = _with_ties(mesh, frame, [vid(0, 0), vid(0, right_side)], grade)
    return mesh


#: Tie tails: how long, how wide, and how far apart they hang.
TIE_LENGTH_M = 0.085
TIE_WIDTH_M = 0.007
TIE_THICKNESS_M = 0.0012


def _with_ties(mesh: Mesh, frame: BodyFrame, sides: list[int], grade: float) -> Mesh:
    """A string bikini's ties: at each hip a bow, two loops and two tails, where the side string is knotted.

    Separate pieces, as a tie is: tied on, not part of the panels, so a brief with
    ties is still one garment with three openings plus its bows. Hanging straight
    down her hip a tail vanished into her silhouette; a bow stands out from it.
    """
    from wardrobe.geometry.ribbon import ribbon
    from wardrobe.lingerie.blocks.bra import _join

    pieces = [mesh]
    positions = mesh.positions.astype(np.float64)
    up = np.array([0.0, 1.0, 0.0])
    for v in sides:
        knot = positions[v]
        _, _, cx, cz = frame.outline(float(knot[1]))
        out = knot - np.array([cx, knot[1], cz])
        out[1] = 0.0
        out /= max(np.linalg.norm(out), 1e-9)
        ahead = np.cross(up, out)  # round her, toward front or back
        centre = knot + out * 0.006
        for lean in (-1.0, 1.0):
            # A loop: out from the knot and back, leaning front or back and a little up.
            theta = np.linspace(0.0, 2 * math.pi, 17)
            loop = (centre[None, :] + out[None, :] * (0.016 * grade * (1 - np.cos(theta)))[:, None] * 0.5
                    + ahead[None, :] * (lean * 0.018 * grade * np.sin(theta / 2) ** 2)[:, None]
                    + up[None, :] * (0.008 * grade * np.sin(theta))[:, None])
            normals = np.repeat(out[None, :], loop.shape[0], axis=0)
            pieces.append(ribbon(loop, normals, width=TIE_WIDTH_M, thickness=TIE_THICKNESS_M,
                                 name=f"tie-loop-{'a' if lean < 0 else 'b'}"))
            # A tail: down and out, swinging a little to the front or back.
            ts = np.linspace(0.0, 1.0, 9)[:, None]
            drop = TIE_LENGTH_M * grade
            tail = (centre + out * (0.004 + 0.02 * ts) - up * drop * ts + ahead * lean * 0.3 * drop * ts
                    * (1 - 0.5 * ts))
            pieces.append(ribbon(tail, np.repeat(out[None, :], tail.shape[0], axis=0), width=TIE_WIDTH_M,
                                 thickness=TIE_THICKNESS_M, name=f"tie-tail-{'a' if lean < 0 else 'b'}"))
    for piece in pieces[1:]:
        piece.metadata["placed"] = np.ones(piece.vertex_count, dtype=bool)
    joined = _join(pieces)
    joined.metadata["lingerieBrief"]["ties"] = len(pieces) - 1
    return joined


def leg_rings(loop_points: np.ndarray, lower: dict | None, centre_x: float, length: float, steps: int,
              clearance: float) -> list[np.ndarray]:
    """Rings carrying a leg opening down round her thigh: each point keeps its direction round the leg.

    Ring ``k`` is ``length * k / steps`` below each opening point, blended from the
    opening toward the leg's measured section there (centre and radius, plus the
    clearance), fully on it by the last ring.
    """
    legs = (lower or {}).get("legs") or {}
    sign = 1.0 if float(np.mean(loop_points[:, 0])) >= centre_x else -1.0
    table = next((np.asarray(r, dtype=np.float64) for r in legs.values()
                  if r and np.sign(np.median(np.asarray(r)[:, 1]) - centre_x) == sign), None)
    if table is not None:
        table = table[np.argsort(table[:, 0])]
    rings = []
    for k in range(1, steps + 1):
        ring = []
        for p in loop_points:
            y = float(p[1]) - length * k / steps
            if table is not None:
                cx, cz, r = (float(np.interp(y, table[:, 0], table[:, c])) for c in (1, 2, 3))
            else:
                cx, cz, r = centre_x + sign * 0.09, float(p[2]) * 0.2, 0.08
            direction = np.array([p[0] - cx, 0.0, p[2] - cz])
            direction /= max(np.linalg.norm(direction), 1e-9)
            target = np.array([cx, y, cz]) + direction * (r + clearance)
            point = p * (1 - k / steps) + target * (k / steps)
            point[1] = y
            ring.append(point)
        rings.append(np.array(ring))
    return rings


def _extend_legs(frame: BodyFrame, positions: np.ndarray, uvs: np.ndarray, loops: dict[str, list[int]],
                 length: float):
    """A boyshort's legs: each leg opening carried down round her thigh (``leg_rings``).

    The rings are placed (the shell's torso passes leave them) and re-derived from
    the fitted opening after the gusset is seated (``lingerie.fit.after_shell``); the
    last ring is the new leg opening, elastic.
    """
    steps = max(int(math.ceil(length / ROW_STEP_M)), 1)
    lower = frame.params.metadata.get("lowerBody")
    new_points, new_uvs, faces, elastic = [], [], [], []
    base = positions.shape[0]
    record = {}
    for key, loop in loops.items():
        rings = leg_rings(positions[loop], lower, frame.marks.centre_x, length, steps, frame.clearance)
        previous = list(loop)
        ids = []
        for k, ring in enumerate(rings, start=1):
            current = list(range(base + len(new_points), base + len(new_points) + len(loop)))
            new_points.extend(ring)
            new_uvs.extend([[uvs[v, 0], uvs[v, 1] + length * k / steps] for v in loop])
            everything = np.vstack([positions, np.array(new_points)])
            middle = everything[current].mean(axis=0)
            ring_faces = []
            for i in range(len(loop)):
                a, b = previous[i], previous[(i + 1) % len(loop)]
                cc, d = current[(i + 1) % len(loop)], current[i]
                ring_faces += [(a, b, cc), (a, cc, d)]
            # Wound outward from this ring's own middle (her thigh), not her body's axis.
            for n, (a, b, c) in enumerate(ring_faces):
                normal = np.cross(everything[b] - everything[a], everything[c] - everything[a])
                outward = (everything[a] + everything[b] + everything[c]) / 3 - middle
                outward[1] = 0.0
                if float(np.dot(normal, outward)) < 0:
                    ring_faces[n] = (a, c, b)
            (elastic if k == steps else faces).extend(ring_faces)
            previous = current
            ids.append(current)
        record[key] = {"loop": list(map(int, loop)), "rings": ids}
    positions = np.vstack([positions, np.array(new_points)])
    uvs = np.vstack([uvs, np.array(new_uvs)])
    return positions, uvs, faces, elastic, {"length": length, "steps": steps, "legs": record}


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


def _orient_outward(mesh: Mesh, frame: BodyFrame, limit: int | None = None) -> None:
    """Wind every triangle so its normal points away from her: the panels' and the gusset's alike.

    ``limit``: only the first so many triangles (a boyshort's leg rings wind themselves).
    """
    all_tris = mesh.indices.reshape(-1, 3)
    tris = all_tris[:limit] if limit is not None else all_tris
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
    all_tris[: tris.shape[0]] = tris
    mesh.indices = all_tris.reshape(-1).astype(np.uint32)


def _weld_seam_normals(mesh: Mesh, a: list[int], b: list[int]) -> None:
    """The side seam's two copies of each vertex share one normal: no crease shading down her side."""
    n = mesh.normals.astype(np.float64)
    avg = n[a] + n[b]
    avg /= np.maximum(np.linalg.norm(avg, axis=1, keepdims=True), 1e-9)
    n[a] = avg
    n[b] = avg
    mesh.normals = n.astype(np.float32)


__all__ = ["GUSSET_COLUMNS", "GUSSET_ROWS", "build_brief", "gusset_point"]
