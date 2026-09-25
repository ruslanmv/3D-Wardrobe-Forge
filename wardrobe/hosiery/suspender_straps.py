"""The straps: flat ribbons from the belt to the stocking clips, and how hard they pull.

Each strap runs belt tab → (slider) → clasp → clip point. Both ends come from
contracts, never from a formula: the tab from the fitted belt's lower edge
(``FittedBelt``), the clip from the fitted stocking band (``FittedStockingTop``).

**Shape.** A strap is a flat ribbon, 9 mm × 1.2 mm by default, its wide face on
the body (``ribbon``). Its centre line starts as the straight line between its
ends, the way an elastic strap under tension runs, and is then lifted wherever
the body, the belt or the stocking would be in the way: it bridges the hollow at
the top of her thigh and lies over her hip where the hip is proud. "In the way"
is read from a depth map along the strap's own outward direction, built from
her torso and legs (never her arms: an A-pose hand beside the thigh is not
something a strap goes over) and from the layers already fitted.

**Tension.** A strap's length in a pose is the shortest path between its two
posed ends that stays outside her posed body (``taut_length``): her body posed
with its own skin weights, not the strap's. Measuring the strap's own skinned
vertices instead was tried first and is wrong: linear blend skinning bows a
strap whose ends turn apart, and read a seated back strap as 30% stretched when
the distance between its clips had grown by 5%. Rest length is the standing
length plus 1.5% slack. Stretch ≤ 4% is fine, 4–10% a warning, over 10% an
error (HOSIERY_STYLING §4.2); below -5% the strap is slack, which is reported
and is not a fault: a front suspender goes slack when she sits.

**Where the ends go.** In the seated pose the thigh swings 85° about the hip
joint's lateral axis, walking 28° each way. A strap end on the thigh moves
toward or away from the belt by how far both ends sit from that axis *in the
side view*. Straight above its clip, a rear strap's tab is a hand's breadth
behind the axis, and it stretched 16–30% seated on the calibration mannequin.
So the tab is chosen, not assumed (``choose_tab``): every point of the fitted
belt's lower edge on that leg's side is tried and the one with the lowest worst
stretch wins, within a 19° slant and 4 cm from the other tabs. The back clip
sits a third of a turn round the leg (``CLIP_TURNS``), which is how real belts
hang their rear suspenders, from the side-back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate
from wardrobe.hosiery import hardware as kit
from wardrobe.hosiery.contract import CLIPS_FOR, FittedBelt, FittedStockingTop
from wardrobe.hosiery.poses import skin

STRAP_WIDTH_M = 0.009
STRAP_THICKNESS_M = 0.0012
#: Rest length = standing path × (1 + slack).
REST_SLACK = 0.015
#: Stretch thresholds.
STRETCH_WARN = 0.04
STRETCH_ERROR = 0.10
#: Shorter than rest by more than this, a strap is slack: reported, not a fault.
SLACK_BELOW = -0.05
#: How far the strap runs up over the belt, where it is sewn on.
BELT_OVERLAP_M = 0.012
#: Gap kept between the strap's underside and whatever is under it.
GAP_M = 0.0006
#: Sampling along the strap, and the depth map's cell.
PATH_STEP_M = 0.01
DEPTH_CELL_M = 0.008


@dataclass
class Strap:
    name: str
    side: str
    clip: str
    path: np.ndarray
    rest_length: float
    bones: list[tuple[str, ...]]
    weights: list[tuple[float, ...]]
    stretch: dict[str, float] = field(default_factory=dict)
    current: dict[str, float] = field(default_factory=dict)

    def status(self, pose: str) -> str:
        s = self.stretch.get(pose, 0.0)
        if s > STRETCH_ERROR:
            return "error"
        if s > STRETCH_WARN:
            return "warning"
        return "slack" if s < SLACK_BELOW else "ok"


# ----------------------------------------------------------------------
# the ribbon primitive
# ----------------------------------------------------------------------
def ribbon(path: np.ndarray, normals: np.ndarray, *, width: float, thickness: float,
           name: str = "ribbon") -> Mesh:
    """A flat strap along ``path``: rectangular section, wide face on ``normals``.

    ``normals`` are the surface's, one per path point; they are made
    perpendicular to the path, so the ribbon never twists more than the
    surface under it does.
    """
    path = np.asarray(path, dtype=np.float64)
    tangent = np.gradient(path, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    normal = normals - tangent * np.sum(normals * tangent, axis=1, keepdims=True)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    across = np.cross(tangent, normal)
    w, t = width / 2.0, thickness / 2.0
    corners = [(-w, -t), (w, -t), (w, t), (-w, t)]
    points = np.stack([path + a * across + b * normal for a, b in corners], axis=1).reshape(-1, 3)
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    uv = np.column_stack([np.tile([0.0, 1.0, 1.0, 0.0], path.shape[0]), np.repeat(along / width, 4)])
    faces = []
    for i in range(path.shape[0] - 1):
        for k in range(4):
            k2 = (k + 1) % 4
            a, b, c, d = 4 * i + k, 4 * i + k2, 4 * (i + 1) + k2, 4 * (i + 1) + k
            faces += [(a, b, c), (a, c, d)]
    last = 4 * (path.shape[0] - 1)
    faces += [(0, 2, 1), (0, 3, 2), (last, last + 1, last + 2), (last, last + 2, last + 3)]
    mesh = Mesh(positions=points.astype(np.float32), indices=np.array(faces, dtype=np.uint32).reshape(-1),
                uvs=uv.astype(np.float32), metadata={"section": name})
    return mesh.compute_normals()


# ----------------------------------------------------------------------
# where a strap runs
# ----------------------------------------------------------------------
def _depth_map(points: np.ndarray, d: np.ndarray, e1: np.ndarray, a_range, y_range):
    a = points @ e1
    y = points[:, 1]
    keep = (a >= a_range[0]) & (a <= a_range[1]) & (y >= y_range[0]) & (y <= y_range[1])
    a, y, depth = a[keep], y[keep], (points[keep] @ d)
    na = int(np.ceil((a_range[1] - a_range[0]) / DEPTH_CELL_M)) + 1
    ny = int(np.ceil((y_range[1] - y_range[0]) / DEPTH_CELL_M)) + 1
    grid = np.full((na, ny), -np.inf)
    ia = np.clip(((a - a_range[0]) / DEPTH_CELL_M).astype(int), 0, na - 1)
    iy = np.clip(((y - y_range[0]) / DEPTH_CELL_M).astype(int), 0, ny - 1)
    np.maximum.at(grid, (ia, iy), depth)
    # The highest surface within a cell's reach: a strap is not threaded between samples.
    padded = np.pad(grid, 1, constant_values=-np.inf)
    grid = np.max([padded[i:i + na, j:j + ny] for i in range(3) for j in range(3)], axis=0)
    return grid, a_range[0], y_range[0]


def strap_path(tab: np.ndarray, end: np.ndarray, d: np.ndarray, surroundings: np.ndarray,
               thickness: float) -> tuple[np.ndarray, np.ndarray]:
    """The strap's centre line from ``tab`` to ``end`` and the surface normal at each point.

    Straight between the ends, lifted along ``d`` (the strap's outward direction)
    wherever the surface would be above the strap's underside.
    """
    d = np.array([d[0], 0.0, d[2]])
    d /= max(float(np.linalg.norm(d)), 1e-12)
    e1 = np.cross(np.array([0.0, 1.0, 0.0]), d)
    length = float(np.linalg.norm(end - tab))
    n = max(int(np.ceil(length / PATH_STEP_M)), 4) + 1
    path = tab + np.outer(np.linspace(0.0, 1.0, n), end - tab)
    a_values = path @ e1
    a_range = (float(a_values.min()) - 0.03, float(a_values.max()) + 0.03)
    y_range = (float(path[:, 1].min()) - 0.03, float(path[:, 1].max()) + 0.03)
    grid, a0, y0 = _depth_map(surroundings, d, e1, a_range, y_range)
    lift = thickness / 2.0 + GAP_M

    def surface(p):
        i = int(np.clip((p @ e1 - a0) / DEPTH_CELL_M, 0, grid.shape[0] - 1))
        j = int(np.clip((p[1] - y0) / DEPTH_CELL_M, 0, grid.shape[1] - 1))
        return grid[i, j]

    for _ in range(3):  # lift, then smooth, then lift again: no kink, and nothing under the strap
        for k in range(1, n - 1):
            s = surface(path[k])
            if np.isfinite(s) and path[k] @ d < s + lift:
                path[k] = path[k] + d * (s + lift - path[k] @ d)
        path[1:-1] = (path[:-2] + 2 * path[1:-1] + path[2:]) / 4.0
    for k in range(1, n - 1):
        s = surface(path[k])
        if np.isfinite(s) and path[k] @ d < s + lift:
            path[k] = path[k] + d * (s + lift - path[k] @ d)
    # The surface normal: the outward direction, tilted by the depth map's slope across the strap.
    normals = []
    for p in path:
        left, right = surface(p - e1 * DEPTH_CELL_M), surface(p + e1 * DEPTH_CELL_M)
        slope = (right - left) / (2 * DEPTH_CELL_M) if np.isfinite(left) and np.isfinite(right) else 0.0
        normal = d - e1 * float(np.clip(slope, -1.5, 1.5))
        normals.append(normal / np.linalg.norm(normal))
    return path, np.array(normals)


def _blend(a_bones, a_weights, b_bones, b_weights, t: float) -> tuple[tuple[str, ...], tuple[float, ...]]:
    table: dict[str, float] = {}
    for bones, weights, share in ((a_bones, a_weights, 1.0 - t), (b_bones, b_weights, t)):
        total = sum(weights) or 1.0
        for bone, w in zip(bones, weights, strict=True):
            table[bone] = table.get(bone, 0.0) + share * w / total
    ranked = sorted(table.items(), key=lambda item: -item[1])[:4]
    total = sum(w for _, w in ranked) or 1.0
    return tuple(b for b, _ in ranked), tuple(w / total for _, w in ranked)


def _torso_only(bones, weights):
    """A tab's binding without leg bones: the belt is worn on her torso."""
    kept = [(b, w) for b, w in zip(bones, weights, strict=True) if "Leg" not in b]
    if not kept:
        return ("hips",), (1.0,)
    total = sum(w for _, w in kept)
    return tuple(b for b, _ in kept), tuple(w / total for _, w in kept)


# ----------------------------------------------------------------------
# the connector garment
# ----------------------------------------------------------------------
@dataclass
class Connector:
    mesh: Mesh
    straps: list[Strap]
    #: Per vertex: (bone names, weights), in mesh order.
    bones: list[tuple[str, ...]]
    weights: list[tuple[float, ...]]
    hardware_triangles: np.ndarray
    parts: dict[str, int]


def build_connector(belt: FittedBelt, tops: dict[str, FittedStockingTop], surroundings: np.ndarray, *,
                    belt_plan: dict, height: float, judge: dict[str, dict[str, np.ndarray]]) -> Connector:
    """Straps from ``belt`` to each stocking's clips, with the hardware the plan asks for.

    ``judge`` holds the bone transforms of each pose a tab is chosen against.
    """
    count = int(belt_plan.get("strapCount") or 4)
    width = float(belt_plan.get("strapWidthM") or STRAP_WIDTH_M * height / 1.6)
    thickness = float(belt_plan.get("strapThicknessM") or STRAP_THICKNESS_M)
    clasp_on = belt_plan.get("clasp", True)
    slider_on = belt_plan.get("adjuster", True)
    ring_on = belt_plan.get("ring", False)
    meshes: list[Mesh] = []
    bones: list[tuple[str, ...]] = []
    weights: list[tuple[float, ...]] = []
    hardware: list[bool] = []
    straps: list[Strap] = []
    parts = {"clasp": 0, "slider": 0, "ring": 0}
    clasp, slider, ring = kit.clasp_local(), kit.slider_local(), kit.ring_local()
    taken: dict[str, list[int]] = {}

    def add(mesh: Mesh, b, w, is_hardware: bool, per_vertex=None):
        meshes.append(mesh)
        if per_vertex is None:
            bones.extend([b] * mesh.vertex_count)
            weights.extend([w] * mesh.vertex_count)
        else:
            bones.extend(per_vertex[0])
            weights.extend(per_vertex[1])
        hardware.extend([is_hardware] * mesh.triangle_count)

    for side, top in sorted(tops.items()):
        for clip_name in CLIPS_FOR.get(count, CLIPS_FOR[4]):
            clip = top.clips[clip_name]
            up = -clip.tangent
            # The clasp: centred on the grip point, standing on the band, facing out along its normal.
            clasp_top = clip.position + up * (kit.CLASP_H / 2.0) + clip.normal * (thickness / 2 + GAP_M)
            end = clasp_top if clasp_on else clip.position + clip.normal * (thickness / 2 + GAP_M)
            # The tab: the point on the belt's lower edge that keeps this strap's stretch lowest in the
            # poses it is judged in, within a slant limit and clear of the other tabs (see the header).
            index = choose_tab(belt, clip, taken.setdefault(side, []), judge)
            taken[side].append(index)
            tab_point = belt.bottom_ring[index]
            belt_normal = np.array([tab_point[0], 0.0, tab_point[2]]) - np.array(
                [belt.bottom_ring[:, 0].mean(), 0.0, belt.bottom_ring[:, 2].mean()])
            belt_normal /= max(float(np.linalg.norm(belt_normal)), 1e-12)
            tab = tab_point + np.array([0.0, BELT_OVERLAP_M, 0.0]) + belt_normal * (thickness / 2 + GAP_M)
            d = clip.normal
            path, normals = strap_path(tab, end, d, surroundings, thickness)
            tab_bones, tab_weights = _torso_only(*(belt.bones[index], belt.weights[index])) if belt.bones \
                else (("hips",), (1.0,))
            arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
            fraction = arc / max(float(arc[-1]), 1e-9)
            # The top 40% moves with the belt, the bottom 20% with the band, a smooth blend between:
            # so the slider (35% down) and the clasp are each carried by one thing.
            blend = np.clip((fraction - 0.4) / 0.4, 0.0, 1.0)
            blend = blend * blend * (3.0 - 2.0 * blend)
            per_point = [_blend(tab_bones, tab_weights, clip.bones, clip.weights, float(t)) for t in blend]
            strap_mesh = ribbon(path, normals, width=width, thickness=thickness,
                                name=f"strap-{side}-{clip_name}")
            corner = [per_point[i // 4] for i in range(strap_mesh.vertex_count)]  # 4 corners a point
            add(strap_mesh, None, None, False, per_vertex=([c[0] for c in corner], [c[1] for c in corner]))
            straps.append(Strap(name=f"{side}-{clip_name}", side=side, clip=clip_name, path=path,
                                rest_length=float(arc[-1]) * (1.0 + REST_SLACK),
                                bones=[p[0] for p in per_point], weights=[p[1] for p in per_point]))
            if clasp_on:
                part = kit.place(clasp, clip.position + clip.normal * GAP_M, np.cross(up, clip.normal), up,
                                 clip.normal, f"hardware-clasp-{side}-{clip_name}")
                add(part, clip.bones, clip.weights, True)
                parts["clasp"] += 1
            if slider_on:
                k = int(np.searchsorted(fraction, kit.SLIDER_AT))
                k = int(np.clip(k, 1, len(path) - 2))
                along = path[k - 1] - path[k + 1]
                part = kit.place(slider, path[k] + normals[k] * (thickness / 2), np.cross(along, normals[k]),
                                 along, normals[k], f"hardware-slider-{side}-{clip_name}")
                add(part, *per_point[k], True)
                parts["slider"] += 1
            if ring_on:
                part = kit.place(ring, tab - np.array([0.0, BELT_OVERLAP_M + kit.RING_D * 0.35, 0.0]),
                                 np.cross(np.array([0.0, 1.0, 0.0]), belt_normal), np.array([0.0, 1.0, 0.0]),
                                 belt_normal, f"hardware-ring-{side}-{clip_name}")
                add(part, tab_bones, tab_weights, True)
                parts["ring"] += 1
    mesh = concatenate(meshes)
    return Connector(mesh=mesh, straps=straps, bones=bones, weights=weights,
                     hardware_triangles=np.array(hardware, dtype=bool), parts=parts)


#: A strap may lean this far from vertical (horizontal run over drop): about 19°.
MAX_SLANT = 0.35
#: Two straps never hang from within this of each other on the belt.
TAB_SEPARATION_M = 0.04


def choose_tab(belt: FittedBelt, clip, taken: list[int], judge: dict[str, dict[str, np.ndarray]]) -> int:
    """The belt-edge vertex this strap hangs from.

    Straight above the clip was the first rule, and a rear strap from there
    stretched 16–30% seated. A strap's length changes in a pose by how far its
    ends are from the hip's hinge line, seen from the side; the tab is the end
    that can move. So every vertex of the lower edge on this leg's side and
    face is tried, and the one whose worst stretch over the judged poses is
    lowest wins, by the distance between its ends. A strap leans no more than
    ``MAX_SLANT`` and keeps ``TAB_SEPARATION_M`` from the tabs already taken.
    """
    ring = belt.bottom_ring
    centre = ring.mean(axis=0)
    clip_side = np.sign(clip.position[0] - centre[0])
    facing = np.sign(clip.normal[2]) if abs(clip.normal[2]) > 0.3 else 0.0
    best, best_score = None, None
    for index, tab in enumerate(ring):
        if np.sign(tab[0] - centre[0]) != clip_side:
            continue
        if facing and np.sign(tab[2] - centre[2]) not in (facing, 0.0) and abs(tab[2] - centre[2]) > 0.01:
            continue
        drop = tab[1] - clip.position[1]
        run = float(np.hypot(tab[0] - clip.position[0], tab[2] - clip.position[2]))
        if drop <= 0 or run > MAX_SLANT * drop:
            continue
        if any(np.linalg.norm(ring[t] - tab) < TAB_SEPARATION_M for t in taken):
            continue
        rest = float(np.linalg.norm(clip.position - tab))
        worst = -np.inf
        for table in judge.values():
            moved = skin(clip.position[None, :], [clip.bones or ("hips",)], [clip.weights or (1.0,)],
                         table)[0]
            worst = max(worst, float(np.linalg.norm(moved - tab)) / rest - 1.0)
        score = (round(worst, 3), run)
        if best_score is None or score < best_score:
            best, best_score = index, score
    if best is None:  # nothing within the slant limit: the nearest point above the clip
        best = int(np.argmin(np.linalg.norm(ring[:, [0, 2]] - clip.position[[0, 2]], axis=1)))
    return best


def taut_length(start: np.ndarray, end: np.ndarray, points: np.ndarray, normals: np.ndarray,
                lift: float, iterations: int = 40) -> tuple[float, np.ndarray]:
    """The shortest strap from ``start`` to ``end`` that stays ``lift`` outside a posed body.

    String pulling: a straight line, pushed out along the normal of the nearest
    body vertex wherever it is within ``lift`` of it (or inside), then relaxed
    toward straight, repeatedly. It bridges hollows and wraps what is proud,
    which is what an elastic strap between two clips does.
    """
    length = float(np.linalg.norm(end - start))
    n = max(int(np.ceil(length / PATH_STEP_M)), 8) + 1
    path = start + np.outer(np.linspace(0.0, 1.0, n), end - start)
    lo, hi = path.min(axis=0) - 0.1, path.max(axis=0) + 0.1
    near = np.all((points >= lo) & (points <= hi), axis=1)
    pts, nrm = points[near], normals[near]
    if pts.shape[0] > 8000:
        pts, nrm = pts[:: pts.shape[0] // 8000 + 1], nrm[:: pts.shape[0] // 8000 + 1]
    for _ in range(iterations):
        if pts.shape[0]:
            inner = path[1:-1]
            d = np.linalg.norm(inner[:, None, :] - pts[None, :, :], axis=2)
            k = d.argmin(axis=1)
            signed = np.sum((inner - pts[k]) * nrm[k], axis=1)
            push = np.clip(lift - signed, 0.0, None)
            path[1:-1] = inner + nrm[k] * push[:, None]
        path[1:-1] = path[1:-1] * 0.5 + (path[:-2] + path[2:]) * 0.25
    return float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum()), path


def measure_tension(straps: list[Strap], *, tables: dict[str, dict[str, np.ndarray]],
                    bodies: dict[str, tuple[np.ndarray, np.ndarray]], lift: float) -> None:
    """Each strap's taut length over her posed body, per pose; rest is standing plus slack. In place."""
    for strap in straps:
        ends = {}
        for pose, table in tables.items():
            a = skin(strap.path[:1], strap.bones[:1], strap.weights[:1], table)[0]
            b = skin(strap.path[-1:], strap.bones[-1:], strap.weights[-1:], table)[0]
            points, normals = bodies[pose]
            ends[pose] = taut_length(a, b, points, normals, lift)[0]
        strap.rest_length = ends["stand"] * (1.0 + REST_SLACK)
        for pose, length in ends.items():
            strap.current[pose] = length
            strap.stretch[pose] = length / strap.rest_length - 1.0


__all__ = [
    "Connector", "REST_SLACK", "STRAP_THICKNESS_M", "STRAP_WIDTH_M", "STRETCH_ERROR", "STRETCH_WARN", "Strap",
    "build_connector", "measure_tension", "ribbon", "strap_path",
]
