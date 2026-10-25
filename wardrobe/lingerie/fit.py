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


def _arc(positions: np.ndarray, row: list[int]) -> float:
    return float(np.linalg.norm(np.diff(positions[row], axis=0), axis=1).sum())


def seat_gusset(positions: np.ndarray, grid: list[list[int]], points: np.ndarray, normals: np.ndarray,
                clearance: float, *, initial: dict[int, np.ndarray] | None = None,
                hold_cut: bool = True) -> np.ndarray:
    """Seat the gusset's interior rows on her surface; the first and last rows (the seams) stay. In place.

    ``hold_cut`` (GF1) keeps each row near the width it was cut to; see ``_seat_brief_gusset`` for
    the constructions that are seated without it.
    """
    rows = [list(row) for row in grid]
    interior = [v for row in rows[1:-1] for v in row]
    if initial:
        for v, p in initial.items():
            positions[v] = p
    # GF1. Each row's width as cut: seating may curve a row onto her, never squeeze its fabric.
    cut = [_arc(positions, row) for row in rows]
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
    _keep_width(positions, rows)
    for _ in range(WIDEN_ROUNDS if hold_cut else 0):
        if not _keep_cut(positions, rows, cut):
            break
        _push_out_not_sideways(positions, index, pts, nrm, clearance)
    # Last, pushes only, until nothing is inside: relaxing must never leave a vertex in her. Not
    # sideways: where her thighs meet, each side's push out of one thigh is toward her midline,
    # and the rows met there too (zero-width slivers, a row of dark teeth from below).
    _push_out_not_sideways(positions, index, pts, nrm, clearance)
    for _ in range(ITERATIONS):  # whatever that could not clear, out along her own normal
        p = positions[index]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        if push.max() < 1e-5:
            break
        positions[index] = p + normal * push[:, None]
    return positions


def _push_out_not_sideways(positions: np.ndarray, index: np.ndarray, pts: np.ndarray, nrm: np.ndarray,
                           clearance: float) -> None:
    """Out of her, up and forward only, until nothing is inside. In place."""
    for _ in range(ITERATIONS):
        p = positions[index]
        signed, normal = _depth(p, pts, nrm)
        push = np.clip(clearance - signed, 0.0, None)
        if push.max() < 1e-5:
            break
        along = normal * [0.0, 1.0, 1.0]
        along /= np.maximum(np.linalg.norm(along, axis=1, keepdims=True), 1e-9)
        positions[index] = p + along * push[:, None]


#: GF1. The least of its cut width a gusset row may keep across: a knit barely compresses in its own
#: plane. Seated on a reference body whose thighs meet, a 55 mm brief gusset's middle row was 16 mm
#: of fabric and 10 mm across; held to this, its sides ride up her inner thighs, as a gusset's do.
#: Not less: at 90% and 85% the sides stopped in the crease between thigh and trunk, where her skin
#: moves most when she stands wide, and went 0.003 and 0.2 mm into her there
#: (tests/integration/test_second_skin_binding.py); at 95% they sit 0.75 mm clear.
MIN_CUT_SHARE = 0.95
#: And the most: lifted up her thighs after widening, a row gained length the widening did not
#: count, and overshot to half as long again as cut. Held to 1 + the stretch a knit brief is
#: drafted to take across her: FreeSewing Uma's xStretch default, 15% (a designer's allowance,
#: assets/reference/lingerie/patterns/freesewing-uma/uma-draft.json). The pushes that end the
#: seat, so nothing is left inside her, can add a little: ref-f-full's middle row settles at 112%.
MAX_CUT_SHARE = 1.15
#: Widen-then-push rounds: each change is pushed back out of her thighs, up and forward.
WIDEN_ROUNDS = 16


def _keep_cut(positions: np.ndarray, rows: list[list[int]], cut: list[float]) -> bool:
    """Bring each interior row within MIN_CUT_SHARE..MAX_CUT_SHARE of its cut width. In place.

    True when a row was changed. Only across (x), about the row's centre: the pushes after it
    lift the sides out of her thighs up and forward, so a row too wide for the gap between them
    climbs her inner thighs rather than going into them. A share of the way each round (damped):
    the lift adds length, and a full correction overshoots.
    """
    changed = False
    for r in range(1, len(rows) - 1):
        row = rows[r]
        have = _arc(positions, row)
        want = min(max(have, MIN_CUT_SHARE * cut[r]), MAX_CUT_SHARE * cut[r])
        if abs(have - want) < 1e-4 or have < 1e-6:
            continue
        xs = positions[row][:, 0]
        centre = float(xs.mean())
        factor = 1.0 + 0.5 * (want / have - 1.0)
        positions[row, 0] = centre + (xs - centre) * factor
        changed = True
    return changed


#: A gusset row narrower than this has collapsed: a reference body's narrows to about 10 mm between
#: her thighs, as it should, and AvatarSample A's micro thong's rows went to nothing.
COLLAPSED_M = 0.004


def _keep_width(positions: np.ndarray, rows: list[list[int]]) -> None:
    """No interior row collapsed below the straight taper between its seams, none crossed. In place.

    Pushed out of two thighs that touch, a gusset's sides met at her midline: its rows went from
    the front seam's 58 mm to nothing two thirds of the way back (AvatarSample A's micro thong).
    A row is widened about its own centre, keeping its shape; one that collapsed to a point is
    laid out evenly across.
    """
    def width(row):
        return float(np.ptp(positions[row][:, 0]))

    first, last = width(rows[0]), width(rows[-1])
    count = len(rows) - 1
    # The way the columns run across (+x or -x): a collapsed row is laid out the seams' way round,
    # or the strip between would be twisted through itself.
    seam = positions[rows[0]][:, 0]
    across = 1.0 if seam[-1] >= seam[0] else -1.0
    for r in range(1, count):
        row = rows[r]
        target = first + (last - first) * r / count
        have = width(row)
        xs = positions[row][:, 0]
        crossed = (xs[-1] - xs[0]) * across < 0
        # Only a collapsed or crossed row: a row that narrows as it follows her (over the pelvic
        # outlet of a reference body) is right, and widened it went into her.
        if have >= COLLAPSED_M and not crossed:
            continue
        target = max(target, have)
        centre = float(xs.mean())
        if have < 1e-4:
            positions[row, 0] = centre + across * (np.arange(len(row)) / (len(row) - 1) - 0.5) * target
        elif crossed:
            # Squeezed past her midline, the row's sides crossed: unwind it, the seams' way round.
            positions[row, 0] = centre + across * (np.arange(len(row)) / (len(row) - 1) - 0.5) * target
        else:
            positions[row, 0] = centre + (xs - centre) * (target / have)


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
        _hug_front(context, positions, record, clearance)
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
    if record:
        _unfold(positions, mesh.indices.reshape(-1, 3))
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
    if record:
        _sew_gusset(mesh, record)
    mesh.compute_normals()
    if seam is not None:
        n = mesh.normals.astype(np.float64)
        avg = n[seam["a"]] + n[seam["b"]]
        avg /= np.maximum(np.linalg.norm(avg, axis=1, keepdims=True), 1e-9)
        n[seam["a"]] = avg
        n[seam["b"]] = avg
        mesh.normals = n.astype(np.float32)


def _sew_gusset(mesh, record: dict) -> None:
    """Give the gusset its own copies of its two seams' vertices: a sewn seam is a hard edge.

    The gusset shared its seams' vertices with the panels, so each seam vertex's normal was
    the average of a panel facing forward (or back) and a gusset facing down. Across that crease
    the two triangles of every quad shaded on opposite sides of the toon step, one with two
    seam corners and one with one: a row of teeth along the front seam from below. The copies
    stand exactly where the originals stand and are skinned as they are (weights are transferred
    by position, after this), so the seam cannot open; each side shades as its own fabric.
    ``record["gusset"]`` keeps naming the panels' vertices; ``record["gussetSeams"]`` the copies.
    """
    grid = record.get("gusset")
    if not grid or len(grid) < 3:
        return
    inside = {v for row in grid for v in row}
    seams = list(dict.fromkeys(list(grid[0]) + list(grid[-1])))
    tris = mesh.indices.reshape(-1, 3).astype(np.int64)
    own = np.array([set(t.tolist()) <= inside for t in tris])
    _wind_like_panels(tris, own)
    count = mesh.vertex_count
    copy = {v: count + k for k, v in enumerate(seams)}
    remap = np.arange(count + len(seams))
    for v, c in copy.items():
        remap[v] = c
    tris[own] = remap[tris[own]]
    source = np.array(seams, dtype=np.int64)
    mesh.positions = np.vstack([mesh.positions, mesh.positions[source]])
    for name in ("normals", "uvs", "joints", "weights"):
        values = getattr(mesh, name)
        if values is not None and len(values) == count:
            setattr(mesh, name, np.concatenate([values, values[source]]))
    for key, values in list(mesh.metadata.items()):
        if isinstance(values, np.ndarray) and values.ndim >= 1 and values.shape[0] == count:
            mesh.metadata[key] = np.concatenate([values, values[source]])
    mesh.indices = tris.reshape(-1).astype(np.uint32)
    record["gussetSeams"] = [[copy[v] for v in grid[0]], [copy[v] for v in grid[-1]]]
    # What each copy was copied from, for anything the shell measured per vertex before this.
    mesh.metadata["sewnFrom"] = np.concatenate([mesh.metadata.get("sewnFrom", np.empty(0, np.int64)), source])


def _wind_like_panels(tris: np.ndarray, own: np.ndarray) -> None:
    """Wind the gusset's triangles as the panels it is sewn to are wound. In place.

    The gusset was wound before fitting, a triangle at a time, "down" under her crotch; seated, its
    rows sag between her thighs and turn, and whole rows ended wound into her: with the panels
    outward, a double-sided toon material shaded them as the fabric's inside. Orientation is
    carried across shared edges from the panels (an edge runs one way in one triangle and the
    other way in its neighbour), so the gusset is one surface with them, whatever its shape.
    """
    edges: dict[tuple[int, int], list[int]] = {}
    for f, t in enumerate(tris):
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append(f)
    done = ~own.copy()
    queue = list(np.flatnonzero(done))
    while queue:
        g = queue.pop()
        t = tris[g]
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            for f in edges[(min(a, b), max(a, b))]:
                if done[f]:
                    continue
                u = tris[f]
                runs_same = any(int(u[m]) == a and int(u[(m + 1) % 3]) == b for m in range(3))
                if runs_same:
                    tris[f] = u[[0, 2, 1]]
                done[f] = True
                queue.append(f)


#: Passes of the unfolding relax, at most.
UNFOLD_ITERATIONS = 30


def _unfold(positions: np.ndarray, tris: np.ndarray) -> None:
    """Relax the vertices of folded triangles until none is folded. In place.

    Under her crotch a brief's panels meet the gusset where the shell's radial passes are
    meaningless (her vertical axis runs through it), and a few triangles there ended turned
    over against their neighbours: from below, a row of dark teeth across the micro thong's
    front seam on AvatarSample A. A triangle is folded when its normal points against the
    area-weighted normal of its corners; its corners (and only theirs) move half way to the
    mean of their neighbours, a pass at a time. The push out of her follows.
    """
    neighbours = [set() for _ in range(positions.shape[0])]
    for a, b, c in tris:
        neighbours[a] |= {b, c}
        neighbours[b] |= {a, c}
        neighbours[c] |= {a, b}
    rings = [np.fromiter(n, dtype=np.int64) for n in neighbours]
    for _ in range(UNFOLD_ITERATIONS):
        a, b, c = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
        face = np.cross(b - a, c - a)
        corner = np.zeros_like(positions)
        for k in range(3):
            np.add.at(corner, tris[:, k], face)
        folded = np.einsum("ij,ij->i", face, corner[tris].sum(axis=1)) < 0
        if not folded.any():
            return
        moving = np.unique(tris[folded])
        moved = positions.copy()
        for v in moving:
            if rings[v].size:
                moved[v] = positions[v] * 0.5 + positions[rings[v]].mean(axis=0) * 0.5
        positions[moving] = moved[moving]


#: A brief's front over her groin is drawn in to this many clearances, this far above its gusset
#: seam and this far either side of her midline.
HUG_FRONT = 2.0
HUG_FRONT_ABOVE_M = 0.05
HUG_FRONT_ACROSS_M = 0.08
#: Her front at a point is the outermost of her surface within this of it, across and up.
COLUMN_M = 0.006


def _hug_front(context, positions: np.ndarray, record: dict, clearance: float) -> None:
    """Seat a brief's front on her groin, as ``_hug_back`` seats a thong's string. In place.

    Drawn on her outline at each height and only pushed out by the radial passes, the front
    panel spanned the crease between her thigh and her mons a centimetre off her (Model Girl):
    leggings over it followed it out, then stepped in below its leg opening, and that step faced
    down: a dark shield at the front of every pair of leggings. The rows near her groin are
    pushed out of her, drawn in where they stand off more than ``HUG_FRONT`` clearances and
    relaxed along the panel; the waist row and the rows the gusset shares stay where they are.
    """
    rows, count = int(record["rows"]), int(record["columns"])
    heights = record.get("heights") or {}
    seam = float(heights.get("seam", positions[:, 1].min()))
    forward = _forward(context)
    side = positions[record["sideSeam"]["a"]][:, 2].mean()
    centre_x = float(positions[record["centreFront"]][0])
    fixed = {v for row in record["gusset"] for v in row}
    grid = [[k * count + j for j in range(count)] for k in range(rows + 1)]
    moving = [v for row in grid[1:-1] for v in row
              if v not in fixed
              and (positions[v, 2] - side) * forward > 0
              and positions[v, 1] < seam + HUG_FRONT_ABOVE_M
              and abs(positions[v, 0] - centre_x) < HUG_FRONT_ACROSS_M]
    if not moving:
        return
    moving = np.array(moving)
    lo, hi = positions[moving].min(axis=0) - 0.04, positions[moving].max(axis=0) + 0.04
    pts, nrm = _surface(context, lo, hi)
    if pts.shape[0] == 0:
        return
    # Her front at each vertex's (x, y), the outermost of her surface in a narrow column: in a
    # crease at her groin that is her own surface, never her thigh beside it. Judged against
    # the nearest few samples (``_depth``) the thigh won, every point of the crease lay behind
    # its tangent plane, and the panel was held a centimetre and a half off her.
    def front_depth(p: np.ndarray) -> np.ndarray:
        out = np.full(p.shape[0], np.nan)
        for i, (x, y, _z) in enumerate(p):
            column = pts[(np.abs(pts[:, 0] - x) < COLUMN_M) & (np.abs(pts[:, 1] - y) < COLUMN_M)]
            if column.shape[0]:
                out[i] = float((column[:, 2] * forward).max())
        return out

    for _ in range(ITERATIONS // 2):
        p = positions[moving]
        depth = front_depth(p)
        known = np.isfinite(depth)
        z = p[:, 2] * forward
        floor = depth + clearance
        target = depth + HUG_FRONT * clearance
        z = np.where(known & (z > target), target, z)
        z = np.where(known & (z < floor), floor, z)
        positions[moving, 2] = z * forward
        relaxed = positions.copy()
        for v in moving:
            k, j = divmod(int(v), count)
            around = [grid[k - 1][j], grid[k + 1][j]]
            around += [grid[k][j - 1]] if j > 0 else []
            around += [grid[k][j + 1]] if j + 1 < count else []
            relaxed[v] = positions[v] * 0.7 + positions[around].mean(axis=0) * 0.3
        positions[moving] = relaxed[moving]
    p = positions[moving]
    depth = front_depth(p)
    known = np.isfinite(depth)
    z = p[:, 2] * forward
    positions[moving, 2] = np.where(known, np.maximum(z, depth + clearance), z) * forward
    record["hugged"] = moving.tolist()


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
    for drafted in mesh.metadata.get("lingerieReferences") or []:
        # RL4. Seat the gusset the block drafted, not the template's constant it replaced.
        from dataclasses import replace

        width, length = drafted["gussetWidthMm"], drafted["gussetLengthMm"]
        spec = replace(spec, gusset_width_mm=width, gusset_length_mm=length)
    initial = {}
    for r, row in enumerate(grid[1:-1], start=1):
        t = r / (len(grid) - 1)
        for i, v in enumerate(row):
            initial[v] = gusset_point(positions[grid[0][i]], positions[grid[-1][i]], t, i, frame, spec)
    seams = positions[grid[0] + grid[-1]]
    centre = seams.mean(axis=0)
    centre[1] = frame.marks.crotch_y
    points, normals = crotch_surface(context, centre)
    # GF1. A gusset keeps its cut width — for now, the foundation put under her clothes (Auto
    # Foundation, which Try-On asks for on every look; PB1's ``requested_foundation`` is false for
    # it): Sitting (Wide) in a bodycon, its 5.8 mm strip of a crotch became 32-35 mm of fabric.
    # Underwear she asks for is seated as before, byte for byte, until three things are settled,
    # each measured on the 35-piece audit (docs/POSE_CONTACT_QA.md): a boyshort's leg rings hang
    # from its gusset edge, and sides riding up her thighs met them (seated stretch 2.27x ->
    # 2.89x); a thong's string rises from its back seam, and wider rows beside it widened the string
    # through the unfolding after (the V-string's 11.1 -> 15.4 mm: off its spec; the thong's stretch
    # 1.34x -> 1.43x); and the radial index centres a layer over the briefs on the median of every
    # point beneath it, so a guêpière over wider briefs moved 1.3 mm, and its geometry is fixed.
    thong = float((record.get("measures") or {}).get("backCoverage", 1.0)) < THONG_BACK_BELOW
    under_clothes = not getattr(context, "requested_foundation", True)
    hold = under_clothes and not record.get("legExtension") and not thong
    seat_gusset(positions, grid, points, normals, clearance, initial=initial, hold_cut=hold)


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
