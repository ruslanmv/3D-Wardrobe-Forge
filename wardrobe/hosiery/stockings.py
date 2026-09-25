"""Stockings that publish their fitted top: the leg tube, the band, the rolled edge and the seam.

Built only for an outfit with a hosiery plan. Plain legwear still comes from
``procedural.build_legwear``, untouched, so a pair of thigh-highs asked for in
words alone is exactly what it was.

The tube differs from ``build_legwear``'s in three ways, each for the contract:

* **A front-facing frame.** ``sweep`` starts each ring wherever a cross product
  lands, so "round the leg from her front" meant nothing on a stocking. Here
  every ring starts at her back and u is measured from her front, the
  convention ``loft`` uses for torso garments. Side darkening and the back seam
  are then functions of u, and clip points have surface coordinates.
* **The band is its own tube**, rows 1 cm apart, meeting the leg at a
  duplicated ring. Its vertices carry their own UVs (a lace band's tile is not
  the leg's) and their own material, and it is the band the contract reads.
* **Rows at known heights**, recorded in the mesh metadata, so the rings can be
  found again after fitting has moved every vertex.

The rolled edge and the seam are not built with the tube. They are laid on it
*after* fitting, from the fitted rings, and take their skin weights from the
vertices under them: built first, fitting would move them separately from the
surface they sit on, and the seam would float or sink.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.hosiery.contract import (
    CLIP_TURNS,
    GRIP_FRACTION,
    GRIP_MAX_M,
    ClipPoint,
    FittedStockingTop,
    ring_normals,
)

#: Row spacing inside the band and down the leg, metres.
BAND_ROW_M = 0.01
LEG_ROW_M = 0.03
#: The rolled edge: a small tube round the band's top ring.
EDGE_RADIUS_M = 0.0018
EDGE_SEGMENTS = 6
#: The seam's thickness, and how far it stands off the leg.
SEAM_THICKNESS_M = 0.0005
SEAM_LIFT_M = 0.0004
#: Fishnet: diamonds knitted round the leg. A fixed count, as a knitting machine
#: makes it, so the diamonds are larger on the thigh than at the ankle.
FISHNET_DIAMONDS = 30
#: Lace band tile, metres (the lace pattern's own).
LACE_TILE_M = 0.07


def _frame(axis: np.ndarray, forward: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors toward her front and toward +x, perpendicular to the leg's axis."""
    front = np.array([0.0, 0.0, forward]) - axis * forward * float(axis[2])
    front /= max(float(np.linalg.norm(front)), 1e-9)
    side = np.cross(axis, front)
    if side[0] < 0:
        side = -side
    return front, side


def _ring(centre: np.ndarray, axis: np.ndarray, radius: float, segments: int, forward: float,
          outward_sign: float) -> tuple[np.ndarray, np.ndarray]:
    """One ring from her back round to her back again (seam duplicated), and each vertex's u.

    u is in turns from her front centre, positive toward her outside, in
    [-0.5, 0.5]: the back seam is at ±0.5.
    """
    front, side = _frame(axis, forward)
    u = np.linspace(-0.5, 0.5, segments + 1)
    angle = 2.0 * math.pi * u
    outward = side * outward_sign
    points = centre + radius * (np.outer(np.cos(angle), front) + np.outer(np.sin(angle), outward))
    return points, u


def _tube(stations: list[tuple[np.ndarray, float]], axis_of, segments: int, forward: float,
          outward_sign: float, name: str) -> tuple[Mesh, np.ndarray]:
    """A tube through (centre, radius) stations, top first. Returns the mesh and each row's arc."""
    rows, us = [], None
    for centre, radius in stations:
        ring, us = _ring(centre, axis_of(centre), radius, segments, forward, outward_sign)
        rows.append(ring)
    positions = np.vstack(rows)
    arc = np.concatenate([[0.0], np.cumsum([np.linalg.norm(b[0] - a[0]) for (a, _), (b, _) in
                                            zip(stations, stations[1:], strict=False)])])
    ring_n = segments + 1
    faces = []
    for row in range(len(stations) - 1):
        top, below = row * ring_n, (row + 1) * ring_n
        for k in range(segments):
            a, b, c, d = top + k, top + k + 1, below + k + 1, below + k
            faces += [(a, c, b), (a, d, c)]
    uv = np.column_stack([np.tile(us, len(stations)), np.repeat(arc, ring_n)])
    mesh = Mesh(positions=positions.astype(np.float32), indices=np.array(faces, dtype=np.uint32).reshape(-1),
                uvs=uv.astype(np.float32), metadata={"section": name})
    return mesh.compute_normals(), arc


def build_stockings(params, *, top_y: float, plan: dict) -> list[Mesh]:
    """A stocking per leg: its band from ``top_y`` down, then the leg to the foot.

    ``plan`` is the ``stockings`` block of a HosieryPlan, as metadata.
    """
    from wardrobe.geometry.procedural import crotch_y  # the procedural module imports this one

    top_y = min(top_y, crotch_y(params, top_y))
    width = float(plan.get("topWidthM") or 0.035)
    segments = max(params.segments // 2, 16)
    forward = params.forward
    meshes: list[Mesh] = []
    for order, side in enumerate(("left", "right")):
        chain = [params.measurements.bone_positions.get(f"{side}{b}")
                 for b in ("UpperLeg", "LowerLeg", "Foot")]
        if any(p is None for p in chain):
            continue
        hip, knee, foot = (np.asarray(p, dtype=np.float64) for p in chain)
        outward_sign = 1.0 if hip[0] >= (params.measurements.bone_positions.get(
            "hips", np.zeros(3))[0]) else -1.0
        thigh_axis = (knee - hip) / max(float(np.linalg.norm(knee - hip)), 1e-9)
        shin_axis = (foot - knee) / max(float(np.linalg.norm(foot - knee)), 1e-9)

        def axis_of(point, knee=knee, thigh_axis=thigh_axis, shin_axis=shin_axis):
            return thigh_axis if point[1] > knee[1] else shin_axis

        t = float(np.clip((hip[1] - top_y) / max(hip[1] - knee[1], 1e-6), 0.0, 1.0))
        top = hip + (knee - hip) * t
        thigh = max(params.measurements.hip_width_m * 0.2, 0.04) + params.clearance_m
        length = float(np.linalg.norm(knee - top))

        def radius_at(point, top=top, length=length, thigh=thigh, knee=knee, foot=foot):
            if point[1] >= knee[1]:
                s = float(np.linalg.norm(point - top)) / max(length, 1e-6)
                return thigh * (1.0 - 0.3 * s)
            s = float(np.linalg.norm(point - knee)) / max(float(np.linalg.norm(foot - knee)), 1e-6)
            return thigh * (0.7 - 0.2 * s)

        band_rows = max(int(math.ceil(width / BAND_ROW_M)), 2)
        band_stations = [top + thigh_axis * width * k / band_rows for k in range(band_rows + 1)]
        band, _ = _tube([(p, radius_at(p)) for p in band_stations], axis_of, segments, forward,
                        outward_sign, f"hosiery-band-{side}")
        band_top_v = 0.0
        # The leg: from the band's bottom ring down to the foot, 3 cm apart, knee exact.
        leg_points = [band_stations[-1]]
        end = foot + np.array([0.0, params.height * 0.02, 0.0])
        for a, b in ((band_stations[-1], knee), (knee, end)):
            steps = max(int(math.ceil(float(np.linalg.norm(b - a)) / LEG_ROW_M)), 1)
            leg_points += [a + (b - a) * (k / steps) for k in range(1, steps + 1)]
        leg, arc = _tube([(p, radius_at(p)) for p in leg_points], axis_of, segments, forward,
                         outward_sign, f"hosiery-leg-{side}")
        leg.uvs[:, 1] += width  # metres below the band's top, continuous with the band
        for mesh, rows in ((band, band_rows + 1), (leg, len(leg_points))):
            mesh.metadata[f"hosieryTube-{side}-{mesh.metadata['section'].split('-')[1]}"] = {
                "order": order, "rows": rows, "ring": segments + 1, "vertexCount": mesh.vertex_count,
            }
        band.metadata["hosieryBand"] = {"width": width, "topV": band_top_v}
        meshes += [band, leg]
    return meshes


# ----------------------------------------------------------------------
# after fitting
# ----------------------------------------------------------------------
def tube_layout(mesh: Mesh) -> dict[str, dict]:
    """Where each side's band and leg tubes start in the fitted mesh, from the build metadata."""
    entries = []
    for key, value in mesh.metadata.items():
        if key.startswith("hosieryTube-"):
            _, side, part = key.split("-")
            entries.append((value["order"], 0 if part == "band" else 1, side, part, value))
    entries.sort()
    layout: dict[str, dict] = {}
    offset = 0
    for _order, _part_rank, side, part, value in entries:
        layout.setdefault(side, {})[part] = {**value, "start": offset}
        offset += value["vertexCount"]
    return layout


def _rows(mesh: Mesh, entry: dict) -> np.ndarray:
    start, rows, ring = entry["start"], entry["rows"], entry["ring"]
    return mesh.positions[start : start + rows * ring].astype(np.float64).reshape(rows, ring, 3)


def finish_stockings(mesh: Mesh, plan: dict, *, forward: float) -> Mesh:
    """Lay the rolled edge and the back seam on the fitted tubes. Returns a new mesh.

    Each new vertex records the tube vertex it sits on (``hosieryWeightSource``),
    so binding can give it exactly that vertex's weights.
    """
    layout = tube_layout(mesh)
    positions = [mesh.positions.astype(np.float64)]
    uvs = [mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), np.float32)]
    faces = [mesh.indices.reshape(-1, 3).astype(np.int64)]
    sections = list(mesh.metadata.get("sections") or [])
    sources: list[np.ndarray] = []
    count = mesh.vertex_count
    triangles = mesh.triangle_count
    for side, parts in layout.items():
        band = _rows(mesh, parts["band"])
        centre = band[0, :-1].mean(axis=0)
        if plan.get("rolledEdge", True):
            ring = band[0, :-1]
            axis = band[-1, :-1].mean(axis=0) - centre
            axis /= max(float(np.linalg.norm(axis)), 1e-9)
            normals = ring_normals(ring, centre, axis)
            p, f, src = _edge(ring, normals, axis, parts["band"]["start"])
            positions.append(p)
            uvs.append(np.zeros((p.shape[0], 2), np.float32))
            faces.append(f + count)
            sources.append(src)
            sections.append((f"hosiery-edge-{side}", triangles, f.shape[0]))
            count += p.shape[0]
            triangles += f.shape[0]
        if plan.get("seam"):
            leg = _rows(mesh, parts["leg"])
            back = leg[:, 0]  # the ring starts at her back: column 0 is the back centre line
            centre_line = leg[:, :-1].mean(axis=1)
            p, f, src = _seam(back, centre_line, float(plan.get("seamWidthM") or 0.0025),
                              parts["leg"]["start"], parts["leg"]["ring"])
            positions.append(p)
            uvs.append(np.zeros((p.shape[0], 2), np.float32))
            faces.append(f + count)
            sources.append(src)
            sections.append((f"hosiery-seam-{side}", triangles, f.shape[0]))
            count += p.shape[0]
            triangles += f.shape[0]
    if len(positions) == 1:
        return mesh
    out = Mesh(
        positions=np.vstack(positions).astype(np.float32),
        indices=np.vstack(faces).astype(np.uint32).reshape(-1),
        uvs=np.vstack(uvs).astype(np.float32),
        metadata={**mesh.metadata, "sections": sections},
    )
    out.metadata["hosieryWeightSource"] = {
        "first": mesh.vertex_count, "sources": np.concatenate(sources).astype(int).tolist(),
    }
    return out.compute_normals()


def _edge(ring: np.ndarray, normals: np.ndarray, axis: np.ndarray, start: int):
    """A small tube round the band's top ring, resting on its outside."""
    n = ring.shape[0]
    angles = np.linspace(0.0, 2.0 * math.pi, EDGE_SEGMENTS, endpoint=False)
    points, source = [], []
    for i in range(n):
        centre = ring[i] + normals[i] * EDGE_RADIUS_M
        for a in angles:
            points.append(centre + EDGE_RADIUS_M * (math.cos(a) * normals[i] + math.sin(a) * axis))
            source.append(start + i)
    faces = []
    for i in range(n):
        j = (i + 1) % n
        for k in range(EDGE_SEGMENTS):
            k2 = (k + 1) % EDGE_SEGMENTS
            a, b = i * EDGE_SEGMENTS + k, i * EDGE_SEGMENTS + k2
            c, d = j * EDGE_SEGMENTS + k2, j * EDGE_SEGMENTS + k
            faces += [(a, b, c), (a, c, d)]
    return np.array(points), np.array(faces, dtype=np.int64), np.array(source)


def _seam(back: np.ndarray, centre: np.ndarray, width: float, start: int, ring: int):
    """A flat strip down the back centre line of the fitted leg, from the band to the heel."""
    down = np.gradient(back, axis=0)
    down /= np.maximum(np.linalg.norm(down, axis=1, keepdims=True), 1e-9)
    out = back - centre
    out -= down * np.sum(out * down, axis=1, keepdims=True)
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
    across = np.cross(down, out)
    across /= np.maximum(np.linalg.norm(across, axis=1, keepdims=True), 1e-9)
    lift = out * SEAM_LIFT_M
    half = across * width * 0.5
    top = back + lift + out * SEAM_THICKNESS_M
    points = np.vstack([np.column_stack([top - half, top + half]).reshape(-1, 3)])
    faces = []
    for r in range(back.shape[0] - 1):
        a, b, c, d = 2 * r, 2 * r + 1, 2 * r + 3, 2 * r + 2
        faces += [(a, b, c), (a, c, d)]
    source = np.repeat(start + np.arange(back.shape[0]) * ring, 2)
    return points, np.array(faces, dtype=np.int64), source


def copy_seated_weights(mesh: Mesh) -> None:
    """Give the edge and the seam the skin weights of the tube vertices under them."""
    record = mesh.metadata.get("hosieryWeightSource")
    if not record or mesh.joints is None or mesh.weights is None:
        return
    first = int(record["first"])
    sources = np.asarray(record["sources"], dtype=int)
    mesh.joints[first : first + sources.size] = mesh.joints[sources]
    mesh.weights[first : first + sources.size] = mesh.weights[sources]


def stocking_uvs(mesh: Mesh, plan: dict) -> None:
    """Set the UVs each part's material reads, from the fitted tubes' rows and columns.

    Recomputed from the geometry, not from whatever UVs fitting left (a patterned
    material's UVs are scaled by its tile size on the way through):

    * the leg: u in turns round from her front (the side-darkening texture is a
      function of u alone) and v in metres; on fishnet, both in diamonds, a fixed
      number of them round the leg;
    * the band: u and v in lace tiles (only a lace band has a texture).
    """
    layout = tube_layout(mesh)
    if not layout:
        return
    uvs = (mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2))).astype(np.float64)
    for parts in layout.values():
        for part, entry in parts.items():
            first, ring = entry["start"], entry["ring"]
            rows = _rows(mesh, entry)
            turns = np.linspace(-0.5, 0.5, ring)
            perimeter = np.linalg.norm(np.diff(rows, axis=1), axis=2).sum(axis=1)
            step = np.linalg.norm(np.diff(rows.mean(axis=1), axis=0), axis=1)
            if part == "leg" and plan.get("pattern") == "fishnet":
                diamond = np.maximum(perimeter / FISHNET_DIAMONDS, 1e-4)  # as tall as it is wide
                u = turns * FISHNET_DIAMONDS
                v = np.concatenate([[0.0], np.cumsum(step / diamond[1:])])
            elif part == "band":
                u = turns * float(perimeter[0]) / LACE_TILE_M
                v = np.concatenate([[0.0], np.cumsum(step)]) / LACE_TILE_M
            else:
                u = turns
                v = np.concatenate([[0.0], np.cumsum(step)])
            block = np.column_stack([np.tile(u, rows.shape[0]), np.repeat(v, ring)])
            uvs[first : first + block.shape[0]] = block
    mesh.uvs = uvs.astype(np.float32)


# ----------------------------------------------------------------------
# the contract
# ----------------------------------------------------------------------
def publish_stocking_tops(mesh: Mesh, segments, bones: dict, *, forward: float,
                          clip_names: tuple[str, ...] = ("front", "outer", "back"),
                          ) -> dict[str, FittedStockingTop]:
    """Read each fitted, bound band back off the mesh as a ``FittedStockingTop``."""
    layout = tube_layout(mesh)
    out: dict[str, FittedStockingTop] = {}
    for side, parts in layout.items():
        entry = parts["band"]
        rows = _rows(mesh, entry)
        top_ring, bottom_ring = rows[0], rows[-1]
        hip = np.asarray(bones.get(f"{side}UpperLeg"), dtype=np.float64)
        knee = np.asarray(bones.get(f"{side}LowerLeg"), dtype=np.float64)
        axis = (knee - hip) / max(float(np.linalg.norm(knee - hip)), 1e-9)
        centre = top_ring[:-1].mean(axis=0)
        normals = ring_normals(top_ring, centre, axis)
        width = float(np.mean(np.linalg.norm(bottom_ring - top_ring, axis=1)))
        centre_x = float(bones.get("hips", np.zeros(3))[0]) if "hips" in bones else 0.0
        outward = 1.0 if hip[0] >= centre_x else -1.0
        clips = {}
        grip = min(width * GRIP_FRACTION, GRIP_MAX_M)
        for name in clip_names:
            clips[name] = _clip(name, side, CLIP_TURNS[name], grip, rows, entry, mesh, segments, axis,
                                forward, outward, width)
        out[side] = FittedStockingTop(
            side=side, top_y=float(top_ring[:-1, 1].mean()), bottom_y=float(bottom_ring[:-1, 1].mean()),
            top_ring=top_ring[:-1], bottom_ring=bottom_ring[:-1], normals=normals[:-1], width_m=width,
            axis_origin=hip, axis=axis, clips=clips,
        )
    return out


def _clip(name, side, turns, grip, rows, entry, mesh, segments, axis, forward, outward, width) -> ClipPoint:
    """The band surface point ``turns`` round from her front, ``grip`` below the top edge."""
    ring_n = entry["ring"]
    u = np.linspace(-0.5, 0.5, ring_n)
    # The tube was built with u positive toward her outside, on either leg.
    k = float(np.interp(turns, u, np.arange(ring_n)))
    k0 = int(np.floor(k))
    k1 = min(k0 + 1, ring_n - 1)
    f = k - k0
    # Down the band to the grip depth: rows are BAND_ROW_M-ish apart, interpolate by arc.
    column = rows[:, k0] * (1 - f) + rows[:, k1] * f
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(column, axis=0), axis=1))])
    v = min(grip, float(arc[-1]))
    position = np.array([np.interp(v, arc, column[:, c]) for c in range(3)])
    row = int(np.clip(np.searchsorted(arc, v), 0, rows.shape[0] - 1))
    tangent = column[min(row + 1, rows.shape[0] - 1)] - column[max(row - 1, 0)]
    tangent /= max(float(np.linalg.norm(tangent)), 1e-9)
    centre = rows[row, :-1].mean(axis=0)
    normal = ring_normals(position[None, :], centre, axis)[0]
    vertex = entry["start"] + row * ring_n + (k0 if f < 0.5 else k1)
    bones, weights = (), ()
    if mesh.joints is not None and mesh.weights is not None:
        pairs = [(segments[int(j)].name, float(w)) for j, w in zip(mesh.joints[vertex], mesh.weights[vertex],
                                                                    strict=True) if w > 0]
        bones, weights = tuple(p[0] for p in pairs), tuple(p[1] for p in pairs)
    return ClipPoint(name=name, side=side, position=position, normal=normal, tangent=tangent,
                     u=turns, v=v, vertex=int(vertex), bones=bones, weights=weights)


__all__ = [
    "build_stockings",
    "copy_seated_weights",
    "finish_stockings",
    "publish_stocking_tops",
    "stocking_uvs",
    "tube_layout",
]
