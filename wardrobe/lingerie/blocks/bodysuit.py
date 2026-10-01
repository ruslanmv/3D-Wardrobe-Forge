"""L5. The bodysuit block: a brief carried up her torso to a neckline, with straps over her shoulders.

The sweep found the one-piece swimsuit and the bodysuit built as the haul's lofted
band: a tube from chest to hips with a hem at each end, open underneath, no leg
openings and no neckline — the one garment in the set that did not look like
itself from any angle. A one-piece is cut as a brief whose top edge is not a
waistline but a neckline, so this is built as exactly that
(``build_brief(top_line=...)``): the same gusset, the same leg openings, the same
coverage-solved leg line the sweep already checked, and a top edge that runs:

* across her front as the style's **neckline** — ``scoop`` (a U), ``plunge`` (a V
  to between her bust points), ``high``, ``square`` — between two **strap points**
  over her bust points, where it peaks;
* down from each strap point into an **armhole** that clears her armpit, level
  round her side;
* up her back to the **back strap points** and down again to the **back** line:
  ``high`` at her shoulder blades, ``scoop`` mid-back, ``low`` to her waist.

Heights are her landmarks' (bust points, the fold under her bust, waist), so one
spec grades across bodies. The leg line is still solved against the brief's own
waistline: a coverage fraction is of the panel from waist to gusset.

**Above the fold the panels are placed, not conformed.** The shell's radial passes
push a panel out from her axis to what they find there, and at the height of her
bust on a spread-armed form what they find at her sides is her arms — the bra
band stood 9–10 cm off her there until it was placed (L4). So, as the band is, the
upper panels are drafted on her measured outline at the clearance — which bridges
between her bust points, as fabric does — and only pushed out of her afterwards
(``wardrobe.lingerie.fit.after_shell``). Below the fold the radial passes fit
the panels to her waist and hips as they fit a brief.

**Straps** are L2 ribbons from each front strap point, sewn a little down the
front as a bra's are (``bra.STRAP_OVERLAP_M``), over her shoulder to the back strap
point on the same side.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.lingerie.blocks.bra import STRAP_ON_CUP_M, STRAP_OVERLAP_M, _join
from wardrobe.lingerie.blocks.brief import build_brief
from wardrobe.lingerie.blocks.frame import BodyFrame
from wardrobe.lingerie.contract import Anchor
from wardrobe.lingerie.specs import BodysuitSpec, BriefSpec, StrapBlock
from wardrobe.lingerie.straps import build_ribbon_strap, surface_normal

#: The strap points' height above her bust points, as a fraction of (bust point → fold):
#: where a bra's cup top is (``BraSpec.cup_height``).
STRAP_HEIGHT = 1.1
#: How far down the centre front each neckline goes, as a fraction of (strap point → fold).
NECK_DEPTH = {"scoop": 0.4, "plunge": 0.85, "high": 0.1, "square": 0.3}
#: The back line's height: fold + this × (bust point → fold) for a high back, and as a
#: fraction of (waist → fold) above her waist for the others.
BACK_HIGH = 1.2
BACK_LINE = {"scoop": 0.9, "low": 0.15}
#: The back strap points: this far above the fold, as (bust point → fold) multiples, and
#: this fraction of the front strap points' distance from her midline.
BACK_STRAP_HEIGHT = 1.3
BACK_STRAP_SPREAD = 0.9


def neckline(frame: BodyFrame, spec: BodysuitSpec):
    """The top edge round her, as a function of angle ``phi`` (0 at her centre front), and its key heights."""
    marks, c = frame.marks, frame.clearance
    cx = marks.centre_x
    fold = min(marks.underbust_y.values())
    apex = {side: np.asarray(p, dtype=np.float64) for side, p in marks.bust_points.items()}
    apex_y = float(np.mean([p[1] for p in apex.values()]))
    depth = max(apex_y - fold, 0.03)
    reach = float(np.mean([abs(p[0] - cx) for p in apex.values()]))

    strap_y = apex_y + depth * STRAP_HEIGHT
    front_y = strap_y - (strap_y - fold) * (NECK_DEPTH[spec.neckline] if spec.neck_depth is None
                                           else spec.neck_depth)
    arm_y = strap_y - (strap_y - fold) * spec.armhole
    if spec.back == "high":
        back_y = fold + depth * BACK_HIGH
    else:
        back_y = marks.waist_y + (fold - marks.waist_y) * BACK_LINE[spec.back]
    back_strap_y = max(fold + depth * BACK_STRAP_HEIGHT, back_y)

    a_front, _, _, _ = frame.outline(strap_y)
    phi_s = math.asin(min(spec.strap_offset * reach / max(a_front + c, 1e-6), 0.95))
    a_back, _, _, _ = frame.outline(back_strap_y)
    phi_b = math.asin(min(BACK_STRAP_SPREAD * spec.strap_offset * reach / max(a_back + c, 1e-6), 0.95))
    side = math.pi / 2

    def top(phi: np.ndarray) -> np.ndarray:
        w = np.abs(np.angle(np.exp(1j * np.asarray(phi, dtype=np.float64))))  # 0 front .. pi back
        # Front: the neckline, flat at the centre (a U) or straight-sided (a V), to the strap.
        t = np.clip(w / phi_s, 0.0, 1.0)
        if spec.neckline == "plunge":
            shape = t
        elif spec.neckline == "square":
            s = np.clip((t - 0.8) / 0.2, 0.0, 1.0)
            shape = s * s * (3 - 2 * s)
        else:
            # A U, not a parabola: sampled at the panel's columns a parabola read as a V.
            shape = 1.0 - np.sqrt(np.clip(1.0 - t * t, 0.0, 1.0))
        front = front_y + (strap_y - front_y) * shape
        # The armhole: down from the strap point, level round her side.
        u = np.clip((w - phi_s) / max(side - phi_s, 1e-6), 0.0, 1.0)
        armhole = strap_y + (arm_y - strap_y) * (1 - (1 - u) ** 2)
        # Up her back to the back strap point, flat at the side.
        v = np.clip((w - side) / max(side - phi_b, 1e-6), 0.0, 1.0)
        rising = arm_y + (back_strap_y - arm_y) * v * v
        # The back line, flat at her centre back.
        r = np.clip((w - (math.pi - phi_b)) / max(phi_b, 1e-6), 0.0, 1.0)
        # The back line is a U too (a V only when it is cut low, to her waist).
        back_shape = (1 - r) if spec.back == "low" else 1.0 - np.sqrt(np.clip(1.0 - (1 - r) ** 2, 0.0, 1.0))
        back = back_y + (back_strap_y - back_y) * back_shape
        behind = np.where(w <= math.pi - phi_b, rising, back)
        return np.where(w <= phi_s, front, np.where(w <= side, armhole, behind))

    heights = {"front": front_y, "strap": strap_y, "armhole": arm_y, "backStrap": back_strap_y,
               "back": back_y, "fold": fold, "apex": apex_y,
               "strapAngle": phi_s, "backStrapAngle": phi_b}
    return top, heights


def build_bodysuit(frame: BodyFrame, brief: BriefSpec, spec: BodysuitSpec, straps: StrapBlock, *,
                   name: str = "bodysuit") -> Mesh:
    top, heights = neckline(frame, spec)
    body = build_brief(frame, brief, name=name, top_line=top, top_section="elastic-bodysuit-neck",
                       symmetric=True)
    record = body.metadata["lingerieBrief"]
    rows, count = int(record["rows"]), int(record["columns"])
    positions = body.positions.astype(np.float64)

    # Above the fold the panels keep their drafted place (see the module note): placed.
    fold = heights["fold"]
    panel = np.zeros(body.vertex_count, dtype=bool)
    panel[: (rows + 1) * count] = True
    upper = panel & (positions[:, 1] > fold)
    _drape_front(positions, upper, rows, count, frame)
    body.positions = positions.astype(np.float32)
    body.compute_normals()
    placed = np.asarray(body.metadata["placed"], dtype=bool) | upper
    body.metadata["placed"] = placed

    # ---- straps: front strap point to back strap point, each side.
    pieces = [body]
    fitted, anchors = {}, {}
    if straps.style != "none":
        cx, forward = frame.marks.centre_x, frame.forward
        top_row = np.arange(count)
        _, _, _, cz = frame.outline(heights["strap"])
        facing_front = (positions[top_row, 2] - cz) * forward > 0
        for side, sign in (("left", 1.0), ("right", -1.0)):
            on_side = (positions[top_row, 0] - cx) * sign > 0.01
            lift = straps.strap_spec().thickness_m / 2 + STRAP_ON_CUP_M
            front = _strap_point(positions, top_row[on_side & facing_front], count, rows, "front", frame,
                                 lift)
            back = _strap_point(positions, top_row[on_side & ~facing_front], count, rows, "back", frame,
                                lift)
            if front is None or back is None:
                continue
            anchors[side] = {"front": front.to_dict(), "back": back.to_dict()}
            built = build_ribbon_strap(frame.params, replace(front, side=side), replace(back, side=side),
                                       spec=straps.strap_spec(), name="strap", over_her=True)
            if built is None:
                continue
            mesh, strap = built
            mesh.metadata["placed"] = np.ones(mesh.vertex_count, dtype=bool)
            pieces.append(mesh)
            fitted[side] = strap.to_dict()
    out = _join(pieces)
    out.metadata["lingerieBodysuit"] = {
        "neckline": spec.neckline, "back": spec.back,
        "heights": {k: float(v) for k, v in heights.items()},
        "anchors": anchors, "straps": fitted,
    }
    return out


#: Where her front surface is used rather than her outline: within this fraction of her
#: half-width, fading to the outline by ``FRONT_EDGE`` (past it the depth map is a wall).
FRONT_FULL, FRONT_EDGE = 0.6, 0.85
#: Ease over her bust, as a bra cup has (``BraSpec.cup_ease_mm``): at the bare clearance the
#: shell's 6 mm surface sampling let her outer bust show through between samples.
BUST_EASE_M = 0.003
#: Her bust point's neighbourhood, and the dome the fabric's floor falls away as there.
APEX_REACH_M, APEX_RADIUS_M = 0.03, 0.05
#: Over how much height above the fold the ease grows from nothing to full.
EASE_TAPER_M = 0.03


def _drape_front(positions: np.ndarray, upper: np.ndarray, rows: int, count: int, frame: BodyFrame) -> None:
    """Lay the upper front on her measured front, bridging across her cleavage. In place.

    Drafted on her outline, the upper front ran on an ellipse that passes *inside* her
    bust at the bust points' height; pushed out afterwards along her surface's normals,
    which diverge over a curve, neighbouring rows crossed and folded — the glossy streaks
    across her bust on the first render. So here, as the bra's cups are (L4): on her
    front surface (the depth map) at the clearance, and then, row by row, never below the
    straight line across between her bust points — fabric under tension bridges her
    cleavage, it does not follow it in.
    """
    marks, c, forward = frame.marks, frame.clearance, frame.forward
    cx = marks.centre_x
    fold = min(marks.underbust_y.values())
    for k in range(rows + 1):
        row = np.arange(k * count, (k + 1) * count - 1)  # the last column repeats the first
        row = row[upper[row]]
        if row.size == 0:
            continue
        front = []
        for v in row:
            x, y, z = positions[v]
            a, _, _, cz = frame.outline(float(y))
            if (z - cz) * forward <= 0:
                continue
            # The ease, outward round her, for every upper front vertex: the depth map's and
            # the outline's alike.
            _, _, cxy, _ = frame.outline(float(y))
            radial = np.array([x - cxy, 0.0, z - cz])
            radial /= max(float(np.linalg.norm(radial)), 1e-9)
            # Tapered to nothing at the fold, where the fitted panels below take over at the
            # bare clearance: at full ease there the fabric stepped out 3 mm, a ledge under her bust.
            taper = float(np.clip((y - fold) / EASE_TAPER_M, 0.0, 1.0))
            ease = BUST_EASE_M * taper * taper * (3 - 2 * taper)
            positions[v] += radial * ease
            x, z = positions[v, 0], positions[v, 2]
            off = abs(x - cx) / max(a + c, 1e-6)
            if off >= FRONT_EDGE:
                continue
            surface = frame.surface(float(x), float(y), "front", c + ease)
            if surface is None:
                continue
            blend = float(np.clip((FRONT_EDGE - off) / (FRONT_EDGE - FRONT_FULL), 0.0, 1.0))
            blend = blend * blend * (3 - 2 * blend)
            positions[v, 2] = z + (float(surface[2]) - z) * blend
            front.append(v)
        # Never under her bust point: bilinear between 1 cm cells, the map reads her apex low,
        # and the one vertex there showed through as a speck. A floor over each measured bust
        # point, falling away as a dome of ``APEX_RADIUS_M`` does.
        for v in front:
            for point in marks.bust_points.values():
                d = float(np.hypot(positions[v, 0] - point[0], positions[v, 1] - point[1]))
                if d < APEX_REACH_M:
                    floor = float(point[2]) * forward + c + BUST_EASE_M - d * d / (2 * APEX_RADIUS_M)
                    positions[v, 2] = max(positions[v, 2] * forward, floor) * forward
        if len(front) < 3:
            continue
        # The row's upper hull across her front, in (x, how far forward): what it bridges.
        front = np.array(sorted(front, key=lambda v: positions[v, 0]))
        xs = positions[front, 0]
        depth = positions[front, 2] * forward
        hull = [0]
        for i in range(1, len(front)):
            while len(hull) >= 2:
                x0, d0 = xs[hull[-2]], depth[hull[-2]]
                x1, d1 = xs[hull[-1]], depth[hull[-1]]
                if (x1 - x0) * (depth[i] - d0) - (d1 - d0) * (xs[i] - x0) >= 0:
                    hull.pop()
                else:
                    break
            hull.append(i)
        bridged = np.interp(xs, xs[hull], depth[hull])
        positions[front, 2] = np.maximum(depth, bridged) * forward
    # The side seam's two copies of each vertex are one point: the last column is not
    # draped above, and where the seam faced forward (a curvy form) it opened into holes.
    positions[count - 1:(rows + 1) * count:count] = positions[0:(rows + 1) * count:count]


def _strap_point(positions: np.ndarray, candidates: np.ndarray, count: int, rows: int, face: str,
                 frame: BodyFrame, lift: float) -> Anchor | None:
    """Where a strap is sewn: at the top edge's peak on this side, a little down the panel, on it."""
    if candidates.size == 0:
        return None
    heights = positions[candidates, 1]
    column = int(candidates[np.argmax(heights)])
    peak = positions[column]
    at = peak
    for k in range(1, rows + 1):
        below = positions[k * count + column]
        at = below
        if np.linalg.norm(below - peak) >= STRAP_OVERLAP_M:
            break
    n = surface_normal(frame.params, float(at[0]), float(at[1]), face)
    if n is None:
        n = np.array([0.0, 0.0, frame.forward * (1.0 if face == "front" else -1.0)])
    at = at + n * lift
    up = np.array([0.0, 1.0, 0.0])
    tangent = up - n * float(np.dot(up, n))
    return Anchor(name=f"bodysuit-{face}-strap", side="", position=at, normal=n,
                  tangent=tangent / max(np.linalg.norm(tangent), 1e-9), source="bodysuit", vertex=column)


__all__ = ["build_bodysuit", "neckline"]
