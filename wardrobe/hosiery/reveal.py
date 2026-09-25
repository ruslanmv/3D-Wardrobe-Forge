"""Reveal: how much of the stocking tops a hem shows, standing, walking and seated, and the hem that gives it.

    discreet   covered standing, walking and seated     "midi or knee length: completely hidden"
    glimpse    covered standing and walking, shows seated "mini: an occasional glimpse"
    statement  band and clips show standing              "lingerie as outerwear"

**Why not just skin the dress.** A dress is bound to her hips and spine. Posed
seated, her thighs rotate 85° and the dress does not, so skinned geometry says
the thighs pass straight through the skirt: everything "shows", whatever the
length. A dress bound to her thighs instead rides along with them, and nothing
ever shows. Neither is what cloth does.

**The model: fabric length is conserved.** A skirt's fabric runs from her waist
down each column of her body (front and outer side of each leg). Standing, the
hem on a column is ``ℓ`` metres of surface below the waist. In a pose that
column's surface path is posed with the body, and the fabric lies along it from
the waist, so the hem is ``ℓ`` along the *posed* path. Less the ride-up: a skirt
is a tube, and when the path under its back lengthens (over her seat as she
sits, behind the forward thigh as she walks) the whole hem rises by that much,
times the cut's ease: a bodycon skirt has none to give (1.0), an A-line has
plenty (0.3). The stocking band is posed with her thigh, so its top and bottom
edges have positions along the same posed path, and "covered" is a comparison of
two numbers along one line.

    covered   hem at or below the band's bottom edge + 1.5 cm, on every column
    band      some of the band shows below the hem
    clips     the hem is above the band's top edge by 1.5 cm: band, clasps and strap ends show

**Solving.** Candidate hems are tried every 5 mm from the knee up to where the
builder's own rule stops a hem (a fifth of the thigh below the hip joint), and
the level's rule picks one: the *highest* hem that is still covered where the
level needs it covered (discreet, glimpse), or the *longest* one that still
shows clips standing (statement). A hem word in the prompt ("mini") is kept as a
range, and an explicit length (``explicitHemLength``, or the request's own hem)
wins outright. Whatever was kept, the report says which level the hem actually
achieves and in which poses the band shows. A user's word is never overridden
silently.

**What this does not model.** Drape and folds: fabric is a length along a path,
not a surface. Friction: a skirt that rides up is assumed to stay up. The
ease factors are chosen by cut, not measured. The seated pose has an upright
pelvis. These are the limits of the numbers the report prints.
"""

from __future__ import annotations

import numpy as np

from wardrobe.hosiery.poses import POSES, posed_body, transforms
from wardrobe.hosiery.poses import skin as skin_points

#: Kept between the hem and a band edge for a state to count, metres.
MARGIN_M = 0.015
#: How much of her seat's lengthening lifts the hem, by the outer garment's cut.
EASE = {"sheath": 1.0, "pencil": 1.0, "slim": 0.9, "straight": 0.6, "cocktail": 0.6, "a-line": 0.3,
        "fit-and-flare": 0.3, "wide": 0.3, "ball-gown": 0.2, "oversized": 0.4}
#: Hem words as ranges of the hip-to-ankle drop (the builder's own table is the centre).
HEM_RANGES = {"mini": (0.0, 0.45), "knee": (0.5, 0.7), "midi": (0.7, 0.86), "ankle": (0.86, 0.97),
              "floor": (0.97, 1.0)}
#: Columns the hem is judged on, in turns round each leg from her front.
COLUMNS = {"front": 0.0, "side": 0.25}
#: Where ride-up is read: the back of each leg.
BACK_TURN = 0.5
STEP_M = 0.01
SOLVE_STEP_M = 0.005


# ----------------------------------------------------------------------
# surface paths down her body
# ----------------------------------------------------------------------
def column_path(points: np.ndarray, leg_centre: np.ndarray, direction: np.ndarray,
                top_y: float, bottom_y: float) -> np.ndarray:
    """Her outermost surface in ``direction``, every centimetre from ``top_y`` down to ``bottom_y``.

    Taken in a 3 cm wide strip through the leg's centre line, so a front column
    runs down the front of her belly and thigh, a side column down her hip and
    the outside of her thigh.
    """
    across = np.cross(np.array([0.0, 1.0, 0.0]), direction)
    rows = []
    for y in np.arange(top_y, bottom_y, -STEP_M):
        slab = points[np.abs(points[:, 1] - y) < STEP_M * 0.75]
        if slab.shape[0] == 0:
            continue
        lateral = (slab - leg_centre) @ across
        strip = slab[np.abs(lateral) < 0.015]
        if strip.shape[0] == 0:
            continue
        best = strip[np.argmax(strip @ direction)]
        rows.append([best[0], y, best[2]])
    return np.asarray(rows, dtype=np.float64)


def _weights_for(path: np.ndarray, bones: dict, side: str) -> tuple[list, list]:
    """Inverse-distance skin weights for path points over hips, spine and this leg: how garments bind."""
    names = [n for n in ("hips", "spine", f"{side}UpperLeg") if n in bones]
    children = {"hips": "spine", "spine": "chest", f"{side}UpperLeg": f"{side}LowerLeg"}
    heads = {n: np.asarray(bones[n], dtype=np.float64) for n in names}
    tails = {n: np.asarray(bones.get(children[n], bones[n]), dtype=np.float64) for n in names}
    out_b, out_w = [], []
    for p in path:
        distances = []
        for n in names:
            a, b = heads[n], tails[n]
            t = np.clip(np.dot(p - a, b - a) / max(float(np.dot(b - a, b - a)), 1e-12), 0.0, 1.0)
            distances.append(float(np.linalg.norm(p - (a + t * (b - a)))))
        strength = [1.0 / (d + 0.01) ** 2.5 for d in distances]
        total = sum(strength)
        out_b.append(tuple(names))
        out_w.append(tuple(s / total for s in strength))
    return out_b, out_w


def _arc(path: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])


def _arc_of(path: np.ndarray, arc: np.ndarray, point: np.ndarray) -> float:
    """Arc position along ``path`` of the point on it nearest ``point``."""
    a, b = path[:-1], path[1:]
    ab = b - a
    t = np.clip(np.sum((point - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
    d = np.linalg.norm(a + t[:, None] * ab - point, axis=1)
    k = int(np.argmin(d))
    return float(arc[k] + t[k] * np.linalg.norm(ab[k]))


# ----------------------------------------------------------------------
# the model
# ----------------------------------------------------------------------
class RevealModel:
    """Where a hem ring sits on each thigh, in each pose, for a hem cut at a given height.

    Positions on a thigh are ``d``: metres along it from the hip joint. Every
    length is taut, the shortest path over her posed body (``taut_length``), the
    way fabric lies over her, bridging the fold at her hip crease.

    Per leg and column (front, outer side, back), standing and posed: the taut
    path from her waist to the thigh's surface at the knee, and how far along it
    each thigh position ``d`` lies. A hem cut at height ``h`` gives each column
    a fabric length (its standing arc to ``d(h)``); posed, that length reaches
    ``d_c`` down the thigh. A skirt is a closed tube, so its hem is one ring round
    each thigh, at the ``d`` of the column that runs out first: the back, over
    her seat, when she sits; the front of a leg swung back, when she walks. A cut
    with ease lets each column hang more on its own: the ring's ``d`` seen from
    the front is ``ease · min + (1 - ease) · d_front``.
    """

    def __init__(self, points: np.ndarray, tops: dict, bones: dict, forward: float, *, ease: float,
                 waist_y: float, bodies: dict[str, tuple[np.ndarray, np.ndarray]]):
        from wardrobe.hosiery.suspender_straps import taut_length

        self.ease = ease
        self.legs: list[dict] = []
        names = sorted({"hips", "spine", *(f"{s}UpperLeg" for s in tops)} & set(bones))
        tables = {pose: transforms(pose, forward, bones, names) for pose in POSES}
        for side, top in sorted(tops.items()):
            hip = np.asarray(bones[f"{side}UpperLeg"], dtype=np.float64)
            knee = np.asarray(bones[f"{side}LowerLeg"], dtype=np.float64)
            axis = (knee - hip) / max(float(np.linalg.norm(knee - hip)), 1e-9)
            length = float(np.linalg.norm(knee - hip))
            grid = np.arange(0.0, length - 0.02, 0.01)
            centre = top.top_ring.mean(axis=0)
            lateral = np.sign(centre[0] - float(bones.get("hips", np.zeros(3))[0])) or 1.0
            outward = np.array([lateral, 0.0, 0.0])
            front = np.array([0.0, 0.0, forward])
            columns = {}
            for name, turns in (*COLUMNS.items(), ("back", BACK_TURN)):
                direction = np.cos(2 * np.pi * turns) * front + np.sin(2 * np.pi * turns) * outward
                path = column_path(points, centre, direction, waist_y, float(knee[1]) - 0.02)
                if path.shape[0] < 4:
                    continue
                ys = hip[1] + grid * axis[1]
                keep = ys >= path[-1, 1]
                thigh = np.column_stack([np.interp(-ys[keep], -path[:, 1], path[:, c]) for c in range(3)])
                thigh[:, 1] = ys[keep]
                w_bones, w_weights = _weights_for(path[:1], bones, side)
                arcs = {}
                for pose in POSES:
                    anchor = skin_points(path[:1], w_bones, w_weights, tables[pose])[0]
                    posed = skin_points(thigh, [(f"{side}UpperLeg",)] * len(thigh), [(1.0,)] * len(thigh),
                                        tables[pose])
                    _, line = taut_length(anchor, posed[-1], *bodies[pose], 0.004, iterations=25)
                    arc = _arc(line)
                    arcs[pose] = np.maximum.accumulate([_arc_of(line, arc, q) for q in posed])
                columns[name] = {"grid": grid[keep], "arcs": arcs}
            if len(columns) == 3:
                self.legs.append({
                    "side": side, "hip": hip, "axis": axis, "columns": columns,
                    "bandTop": float((top.top_ring.mean(axis=0) - hip) @ axis),
                    "bandBottom": float((top.bottom_ring.mean(axis=0) - hip) @ axis),
                })

    @staticmethod
    def _reach(column: dict, pose: str, fabric: float) -> float:
        """How far down the thigh ``fabric`` metres of this column reach in ``pose``."""
        arcs, grid = column["arcs"][pose], column["grid"]
        if fabric >= arcs[-1]:
            return float(grid[-1] + (fabric - arcs[-1]))
        return float(np.interp(fabric, arcs, grid))

    def ring(self, leg: dict, hem_y: float, pose: str) -> float:
        """The hem ring's position ``d`` down this thigh in ``pose``, for a hem cut at ``hem_y``."""
        d_hem = float((hem_y - leg["hip"][1]) / leg["axis"][1])
        reach = {}
        for name, column in leg["columns"].items():
            fabric = float(np.interp(d_hem, column["grid"], column["arcs"]["stand"]))
            reach[name] = self._reach(column, pose, fabric)
        return self.ease * min(reach.values()) + (1.0 - self.ease) * reach["front"]

    def states(self, hem_y: float) -> dict[str, dict]:
        out = {}
        for pose in POSES:
            covers, clears = [], []
            for leg in self.legs:
                d = self.ring(leg, hem_y, pose)
                covers.append(d - leg["bandBottom"])
                clears.append(leg["bandTop"] - d)
            covered = min(covers) >= MARGIN_M
            clips = min(clears) >= MARGIN_M
            out[pose] = {"state": "covered" if covered else "clips" if clips else "band",
                         "coverMm": round(min(covers) * 1000.0, 1)}
        return out


def achieved(states: dict[str, dict]) -> tuple[str, list[str]]:
    visible = [pose for pose in POSES if states[pose]["state"] != "covered"]
    if "stand" in visible:
        return "statement", visible
    return ("glimpse" if visible else "discreet"), visible


def _meets(level: str, states: dict) -> bool:
    """The rule for each level, strictly: glimpse is covered standing *and walking*, shown seated."""
    shown = {pose: states[pose]["state"] != "covered" for pose in POSES}
    if level == "statement":
        return states["stand"]["state"] == "clips"
    if level == "glimpse":
        return not shown["stand"] and not shown["walk"] and shown["sit"]
    return not any(shown.values())


def posed_bodies(context) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Her body round the hips and thighs, posed, once per job: the straps and the hem share it."""
    cached = context.hosiery_bodies
    if cached is not None:
        return cached
    from wardrobe.hosiery.fit import forward
    from wardrobe.vrm.skinning import ARM_BONES

    pivots = context.measurements.bone_positions
    hip_y = float(pivots.get("hips", (0.0, 1.0, 0.0))[1])
    reach = context.measurements.height_m * 0.35
    region = (np.array([-reach, hip_y - reach, -reach]), np.array([reach, hip_y + reach * 0.5, reach]))
    facing = forward(context)
    bodies = {pose: posed_body(context.document, context.info, pose, facing, pivots, exclude_bones=ARM_BONES,
                               region=region) for pose in POSES}
    context.hosiery_bodies = bodies
    return bodies


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------
def solve_hem(context, reveal: dict) -> dict:
    """The hem for ``reveal`` on this outfit's outer garment, and what it achieves in each pose."""
    from wardrobe.engines.geometry_checks import body_points
    from wardrobe.engines.shell import _torso
    from wardrobe.geometry.procedural import FitParameters
    from wardrobe.hosiery.fit import forward

    level = reveal.get("level", "glimpse")
    bones = context.measurements.bone_positions
    params = FitParameters(measurements=context.measurements)
    whole = body_points(context.document)
    torso = _torso(context, whole)
    points = torso if torso is not None and torso.shape[0] else whole
    if context.collision_points is not None:
        points = np.vstack([points, context.collision_points])
    silhouette = context.plan.silhouette if context.plan is not None else "straight"
    conform = float(context.artifact.metadata.get("conform") or 0.0)
    ease = 1.0 if conform >= 0.9 else EASE.get(silhouette, 0.6)
    model = RevealModel(points, context.stocking_tops, bones, forward(context), ease=ease,
                        waist_y=params.waist_y, bodies=posed_bodies(context))
    if not model.legs:
        return {"requested": level, "achieved": None,
                "notes": ["the reveal could not be measured on this body"]}

    drop = params.hip_y - params.ankle_y
    thigh_fraction = (params.hip_y - params.knee_y) / max(drop, 1e-6)
    lowest = params.knee_y + 0.02
    highest = params.hip_y - drop * thigh_fraction * 0.2  # the builder never cuts a hem above this
    notes: list[str] = []
    explicit = reveal.get("explicitHemLength")
    prompt_hem = reveal.get("promptHem")

    if explicit is not None:
        if isinstance(explicit, str):
            centre = {"mini": 0.34, "knee": 0.62, "midi": 0.78, "ankle": 0.94, "floor": 1.0}[explicit]
            hem_y = params.hip_y - drop * centre
            reason = f"the {explicit} length asked for"
        else:
            hem_y = params.waist_y - float(explicit) / 100.0
            reason = f"the {float(explicit):g} cm length asked for"
        hem_y = float(np.clip(hem_y, params.ankle_y, highest))
        states = model.states(hem_y)
        got, visible = achieved(states)
        if got != level:
            notes.append(f"kept {reason}; it gives {got}, not {level}")
        return _result(level, got, visible, hem_y, states, notes, explicit=True, ease=ease)

    top_limit, bottom_limit = highest, lowest
    if prompt_hem in HEM_RANGES:
        lo, hi = HEM_RANGES[prompt_hem]
        top_limit = min(highest, params.hip_y - drop * lo)
        bottom_limit = max(params.ankle_y, params.hip_y - drop * hi)
    candidates = np.arange(top_limit, bottom_limit, -SOLVE_STEP_M)
    evaluated = [(float(h), model.states(float(h))) for h in candidates]
    chosen = None
    if level == "statement":
        # The longest hem that still shows the clips standing.
        chosen = next(((h, s) for h, s in reversed(evaluated) if _meets(level, s)), None)
    else:
        chosen = next(((h, s) for h, s in evaluated if _meets(level, s)), None)
    if chosen is None:
        # Nothing in range gives it: the nearest the range allows, and say so.
        ranking = {"discreet": 0, "glimpse": 1, "statement": 2}
        target = ranking[level]
        chosen = min(evaluated, key=lambda item: (abs(ranking[achieved(item[1])[0]] - target),
                                                  item[0] if level != "statement" else -item[0]))
        what = f"a {prompt_hem}" if prompt_hem else "any hem"
        notes.append(f"{what} cannot give {level} on this body; the nearest is {achieved(chosen[1])[0]}")
    hem_y, states = chosen
    got, visible = achieved(states)
    return _result(level, got, visible, hem_y, states, notes, explicit=False, ease=ease)


def _result(level, got, visible, hem_y, states, notes, *, explicit: bool, ease: float) -> dict:
    return {
        "requested": level, "achieved": got, "visibleIn": visible, "hemY": round(float(hem_y), 4),
        "explicitLength": explicit, "marginMm": MARGIN_M * 1000.0, "ease": ease,
        "perPose": states, "notes": notes,
        "summary": f"reveal: requested {level}, achieved {got}"
        + (f" (band visible in: {', '.join(visible)})" if visible else " (band hidden in every pose)"),
    }


__all__ = ["EASE", "HEM_RANGES", "MARGIN_M", "RevealModel", "achieved", "solve_hem"]
