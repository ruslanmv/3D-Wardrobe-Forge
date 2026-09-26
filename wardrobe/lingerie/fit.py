"""Fitting steps a pattern block needs beyond the shell's radial passes.

The shell fits a garment by pushing it out from her vertical axis, which is how
a panel meets a torso. A brief's gusset crosses *under* her, where that axis
runs through the fabric. It is marked ``placed`` so those passes leave it, and
is seated here once the panels round it are fitted (``after_shell``):

1. its two seams are the front and back panels' own lowest vertices, already
   fitted, so it starts from where the panels actually are;
2. each interior row is re-drawn on the curve between them through a point
   under her crotch;
3. then, like a taut strap (``wardrobe.geometry.ribbon.taut_length``), it is
   pushed out of her surface — her body in the rest pose with its own normals,
   sampled across its triangles — wherever it is within the clearance, drawn
   back toward her wherever it hangs off, and relaxed across and along, a few
   dozen times. It ends on her surface, following it, at the clearance.
"""

from __future__ import annotations

import numpy as np

from wardrobe.lingerie.blocks.brief import GUSSET_COLUMNS, THONG_BACK_BELOW, gusset_point
from wardrobe.lingerie.blocks.frame import body_frame
from wardrobe.lingerie.specs import parse_block

ITERATIONS = 40
#: A gusset further off her than this many clearances is drawn back in.
HUG = 2.0


def _forward(context) -> float:
    from wardrobe.vrm.inspect import VrmSpec

    return -1.0 if context.info.spec is VrmSpec.VRM0 else 1.0


def crotch_surface(context, centre: np.ndarray, reach: float = 0.16) -> tuple[np.ndarray, np.ndarray]:
    """Her surface, points and outward normals, in a box round her crotch, rest pose."""
    from wardrobe.hosiery.poses import posed_body
    from wardrobe.vrm.skinning import ARM_BONES

    lo, hi = centre - reach, centre + reach
    return posed_body(context.document, context.info, "stand", _forward(context),
                      context.measurements.bone_positions, exclude_bones=frozenset(ARM_BONES),
                      spacing=0.006, region=(lo, hi))


def seat_gusset(positions: np.ndarray, grid: list[list[int]], points: np.ndarray, normals: np.ndarray,
                clearance: float, *, initial: dict[int, np.ndarray] | None = None) -> np.ndarray:
    """Seat the gusset's interior rows on her surface; the first and last rows (the seams) stay. In place."""
    rows = [list(row) for row in grid]
    interior = [v for row in rows[1:-1] for v in row]
    if initial:
        for v, p in initial.items():
            positions[v] = p
    if points.shape[0] == 0 or not interior:
        return positions
    pts, nrm = points, normals
    if pts.shape[0] > 12000:
        step = pts.shape[0] // 12000 + 1
        pts, nrm = pts[::step], nrm[::step]
    index = np.array(interior)
    for _ in range(ITERATIONS):
        p = positions[index]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        pull = np.clip(signed - HUG * clearance, 0.0, None) * 0.5
        positions[index] = p + normal * (push - pull)[:, None]
        # Relax toward the neighbours (along the gusset and across it); seams fixed.
        relaxed = positions.copy()
        for r in range(1, len(rows) - 1):
            for i, v in enumerate(rows[r]):
                around = [rows[r - 1][i], rows[r + 1][i]]
                if i > 0:
                    around.append(rows[r][i - 1])
                if i < len(rows[r]) - 1:
                    around.append(rows[r][i + 1])
                relaxed[v] = positions[v] * 0.5 + positions[around].mean(axis=0) * 0.5
        positions[index] = relaxed[index]
    # Last, pushes only, until nothing is inside: relaxing must never leave a vertex in her.
    for _ in range(ITERATIONS):
        p = positions[index]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        if push.max() < 1e-5:
            break
        positions[index] = p + normal * push[:, None]
    return positions


#: A vertex is judged against this many of its nearest surface samples.
NEIGHBOURS = 8


def _depth(p: np.ndarray, pts: np.ndarray, nrm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """How far each point is outside her, and which way is out, from its nearest samples.

    One nearest sample misjudges a corner: in the V between trunk and thigh the
    nearest point can be on the thigh, whose normal says "outside" for a vertex
    that is inside the trunk. The deepest of the nearest few is believed.
    """
    d = np.linalg.norm(p[:, None, :] - pts[None, :, :], axis=2)
    count = min(NEIGHBOURS, pts.shape[0])
    near = np.argpartition(d, count - 1, axis=1)[:, :count]
    signed_all = np.einsum("ijk,ijk->ij", p[:, None, :] - pts[near], nrm[near])
    worst = signed_all.argmin(axis=1)
    rows = np.arange(p.shape[0])
    return signed_all[rows, worst], nrm[near[rows, worst]]


def after_shell(context, mesh, clearance: float) -> None:
    """Seat what the radial passes left (``placed``), then make sure none of it is inside her.

    A brief's gusset is seated between its seams (``seat_gusset``). Then every
    placed vertex — cups, the band's front, straps, the gusset — is checked
    against her posed surface and pushed out to the clearance where it is not
    clear: a 1 cm depth map is a good guide on her chest and a poor one where
    it turns into her armpit and shoulder, and a strap there read 15 mm inside.
    """
    placed = mesh.metadata.get("placed")
    if placed is None or not np.any(placed):
        return
    positions = mesh.positions.astype(np.float64)
    record = mesh.metadata.get("lingerieBrief")
    seam = None
    if record:
        # The side seam's two copies of each vertex were fitted one at a time and can
        # have drifted apart by a fraction of a millimetre: sewn is sewn, rejoin them.
        seam = record["sideSeam"]
        joined = (positions[seam["a"]] + positions[seam["b"]]) / 2
        positions[seam["a"]] = joined
        positions[seam["b"]] = joined
        if float((record.get("measures") or {}).get("backCoverage", 1.0)) < THONG_BACK_BELOW:
            _hug_back(context, positions, record, clearance)
        _seat_brief_gusset(context, mesh, positions, record, clearance)
        extension = record.get("legExtension")
        if extension:
            # A boyshort's legs hang from the openings as fitted, gusset edge included.
            from wardrobe.lingerie.blocks.brief import leg_rings

            frame_meta = _frame_metadata(mesh)
            centre = (frame_meta.get("lingerieLandmarks") or {}).get("centre_x", 0.0)
            for leg in extension["legs"].values():
                rings = leg_rings(positions[leg["loop"]], frame_meta.get("lowerBody"), float(centre),
                                  extension["length"], extension["steps"], clearance)
                for ids, ring in zip(leg["rings"], rings, strict=True):
                    positions[ids] = ring
    index = np.flatnonzero(placed)
    lo, hi = positions[index].min(axis=0) - 0.04, positions[index].max(axis=0) + 0.04
    points, normals = _surface(context, lo, hi)
    if points.shape[0]:
        for _ in range(ITERATIONS):
            p = positions[index]
            signed, normal = _depth(p, points, normals)
            push = np.clip(clearance - signed, 0.0, None)
            if push.max() < 1e-5:
                break
            positions[index] = p + normal * push[:, None]
    mesh.positions = positions.astype(np.float32)
    mesh.compute_normals()
    if seam is not None:
        n = mesh.normals.astype(np.float64)
        avg = n[seam["a"]] + n[seam["b"]]
        avg /= np.maximum(np.linalg.norm(avg, axis=1, keepdims=True), 1e-9)
        n[seam["a"]] = avg
        n[seam["b"]] = avg
        mesh.normals = n.astype(np.float32)


#: A string is drawn in only to this many clearances: it bridges the cleft of her seat,
#: which the 6 mm surface sampling cannot resolve; drawn in to ``HUG`` it went inside her.
HUG_BACK = 4.0


def _hug_back(context, positions: np.ndarray, record: dict, clearance: float) -> None:
    """Seat a thong's back on her, the way the gusset is: it followed her outline, not her.

    The panels are drawn on her measured outline at each height, which spans straight
    across her seat, and the radial passes only push out. A full back is right to
    bridge it; a thong's string is not: running under her seat to the gusset it stood
    off her by up to 41 mm on the fit form, a flap behind her in profile, twisted where
    it met the gusset seam. Every row of the string but the waistband's is pushed out of
    her, drawn back in where it hangs off (``HUG_BACK`` clearances) and relaxed along and
    across, as ``seat_gusset`` does; the gusset is then seated from the back seam this
    leaves.
    """
    from wardrobe.lingerie.blocks.brief import GUSSET_COLUMNS, LEG_HALF_COLUMNS

    rows, count = int(record["rows"]), int(record["columns"])
    # The string's own columns: they alone run down to the gusset seam, so they share one
    # row structure. Seated with the straps beside them, relaxing dragged the straps down
    # over her seat into a wide triangle.
    first = LEG_HALF_COLUMNS + GUSSET_COLUMNS + 2 * LEG_HALF_COLUMNS
    columns = list(range(first, first + GUSSET_COLUMNS + 1))
    grid = [[k * count + j for j in columns] for k in range(rows + 1)]
    moving = np.array([v for row in grid[1:] for v in row])
    lo, hi = positions[moving].min(axis=0) - 0.04, positions[moving].max(axis=0) + 0.04
    pts, nrm = _surface(context, lo, hi)
    if pts.shape[0] == 0:
        return
    for _ in range(ITERATIONS):
        p = positions[moving]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        pull = np.clip(signed - HUG_BACK * clearance, 0.0, None) * 0.5
        positions[moving] = p + normal * (push - pull)[:, None]
        relaxed = positions.copy()
        for r in range(1, len(grid)):
            for i, v in enumerate(grid[r]):
                around = [grid[r - 1][i]] + ([grid[r + 1][i]] if r + 1 < len(grid) else [])
                around += [grid[r][i - 1]] if i > 0 else []
                around += [grid[r][i + 1]] if i + 1 < len(grid[r]) else []
                relaxed[v] = positions[v] * 0.5 + positions[around].mean(axis=0) * 0.5
        positions[moving] = relaxed[moving]
    for _ in range(ITERATIONS):  # relaxing must never leave a vertex in her
        p = positions[moving]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        if push.max() < 1e-5:
            break
        positions[moving] = p + normal * push[:, None]


def _seat_brief_gusset(context, mesh, positions: np.ndarray, record: dict, clearance: float) -> None:
    from wardrobe.geometry.procedural import FitParameters

    grid = record["gusset"]
    params = FitParameters(measurements=context.measurements, clearance_m=clearance,
                           metadata={**(context.artifact.metadata or {}), **_frame_metadata(mesh)})
    frame = body_frame(params)
    spec = parse_block("brief-block", params.metadata.get("lingerie") or {}).brief
    initial = {}
    for r, row in enumerate(grid[1:-1], start=1):
        t = r / (len(grid) - 1)
        for i, v in enumerate(row):
            initial[v] = gusset_point(positions[grid[0][i]], positions[grid[-1][i]], t, i, frame, spec)
    seams = positions[grid[0] + grid[-1]]
    centre = seams.mean(axis=0)
    centre[1] = frame.marks.crotch_y
    points, normals = crotch_surface(context, centre)
    seat_gusset(positions, grid, points, normals, clearance, initial=initial)


def _surface(context, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Her surface in a box, rest pose, arms left out (an A-pose arm is not what a strap lies on)."""
    from wardrobe.hosiery.poses import posed_body
    from wardrobe.vrm.skinning import ARM_BONES

    return posed_body(context.document, context.info, "stand", _forward(context),
                      context.measurements.bone_positions, exclude_bones=frozenset(ARM_BONES),
                      spacing=0.006, region=(lo, hi))


def _frame_metadata(mesh) -> dict:
    """The landmarks and outline the block was drafted on, kept with it for the steps after."""
    return mesh.metadata.get("lingerieFrame") or {}


__all__ = ["GUSSET_COLUMNS", "after_shell", "crotch_surface", "seat_gusset"]
