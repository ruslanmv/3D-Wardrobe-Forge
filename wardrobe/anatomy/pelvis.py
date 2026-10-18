"""AN-A2. Her pelvic outlet from a reviewed atlas, fitted to her, not sculpted from guesses.

MakeHuman's template closes the space between her thighs with a plateau: at her crotch point a
coronal section of the median body is flat for about 8 cm, where a woman's is a mound 2-3 cm
wide between two folds. A thong or a gusset fitted to the plateau was fitted to nothing real,
and a sheer one showed it. ``docs/ANATOMY_ASSETS.md`` records the search for a source: nothing
CC0 in MakeHuman's own assets models the region, and its ``helper-genital`` is a 200-vertex
proxy, not anatomy.

The source is the Human Reference Atlas's female skin (CC BY 4.0; imported and hashed by
``tools/anatomy/import_hra.py``, provenance and attribution in ``assets/anatomy/hra-provenance.json``):
the Visible Human Female's outer surface, segmented by the atlas's anatomists. At its ~5 mm
edges it has the mons, the vulval outer contour as one closed mound, the genitocrural folds
either side of it and the start of the perineum. It is fitted to each reference body:

1. **scaled** by her trunk's breadth and depth 7 cm above her crotch over the scan's (the scan
   is a broader woman), and vertically by their geometric mean;
2. **pitched** about her crotch point to where the scan best agrees with her on a ring 6-13 cm
   out: the scan is of a body frozen lying on its back, and its pelvis is tilted against her
   standing one by about 10 degrees;
3. **mirrored and averaged**: the scan is one woman and not symmetric, the reference bodies are;
   taken as it is, the fit put a fold on one thigh only;
4. **drawn onto it only where it is the anatomy** (``weights``): the mound, widening up into the
   pubic triangle, within 7 cm of her crotch point; not behind the start of the perineum, and not
   below her crotch — the scan's thighs are closer together than a standing body's, and drawn
   onto them her inner thighs became a slit with a wall beside it;
5. **blended**: her surface is moved by a Laplacian-regularised non-rigid fit. Where the weight is
   one the scan decides; around it her own Laplacian coordinates are kept, so the change fades
   into her surface over the 14 cm the fit may touch, and beyond it nothing moves.

The crotch point is the scan's crotch point placed on hers, so her calibrated crotch height is
unchanged; the crotch length, which is taped through this region, is the one dimension that
moves noticeably (about 1 cm shorter, inside its tolerance), and the validation report gives
every dimension after the fit.

The fit takes about a minute per body, so it is not done when a body is built: each size's
displacement is stored in ``assets/anatomy/pelvic-outlet.npz`` by ``tools/anatomy/fit_pelvis.py``,
with a hash of the surface it was fitted to. ``apply`` refuses a stored fit whose surface no
longer matches — after a recalibration, say — and says to re-run the tool, rather than moving
vertices of a body it was not fitted to.

What this is not: the labia minora, the clitoral hood and the vestibule are not in the scan at
its resolution and are not built; the mound is closed, as the scan's is. The surface is rigid,
as the rest of her is (``reference.ANATOMY``).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from wardrobe.anatomy import measure as M
from wardrobe.anatomy.contact import ContactBody

ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "assets" / "anatomy" / "hra-pelvis.npz"
PROVENANCE_PATH = ROOT / "assets" / "anatomy" / "hra-provenance.json"
OUTLET_PATH = ROOT / "assets" / "anatomy" / "pelvic-outlet.npz"

#: Where her trunk is measured to scale the scan (as the importer measured the scan).
SCALE_HEIGHT_M = 0.07
#: The ring the pitch is chosen on, and the pitches tried (degrees).
PITCH_RING_M = (0.06, 0.13)
PITCH_DEGREES = np.arange(-24.0, 25.0, 1.0)
#: Vertices further than this from her crotch point never move.
FREE_RADIUS_M = 0.14
#: The mask (metres on the median body, scaled with her): the mound's half-width at the crotch,
#: how fast it widens going up (into the pubic triangle), and the falloff beside it.
MOUND_HALF_WIDTH_M = 0.012
MOUND_WIDENING = 0.5
MOUND_FALLOFF_M = 0.016
#: ... within this distance of the crotch point (vulva and mons, not the belly), falling off over the next.
CORE_RADIUS_M = (0.07, 0.035)
#: ... not behind this (the perineum's start, not the anus), falling off over the next.
BACK_LIMIT_M = (0.05, 0.02)
#: ... and not below the crotch, where the scan's thighs would draw hers together.
LOW_LIMIT_M = (0.025, 0.015)
#: How far from a vertex the scan is looked for; a vertex with no scan within it is not drawn.
SEARCH_M = 0.04
#: The fit's iterations: closest points, then a solve, this many times.
OUTER_ITERATIONS = 5
CG_ITERATIONS = 400
#: How firmly her own shape (Laplacian coordinates) is kept against the scan's pull.
SMOOTHNESS = 1.0
#: Positions are rounded to this before hashing, so the hash is of the surface, not of float noise.
STAMP_M = 1e-5


@dataclass
class OutletFit:
    indices: np.ndarray  # vertices moved
    delta: np.ndarray  # their displacement, metres
    report: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def patch() -> tuple[np.ndarray, np.ndarray, float, float]:
    """(vertices, triangles, trunk breadth, trunk depth) of the imported scan region, crotch at the origin."""
    data = np.load(PATCH_PATH)
    return (
        data["vertices"].astype(np.float64),
        data["faces"].astype(np.int64),
        float(data["breadth"]),
        float(data["depth"]),
    )


@lru_cache(maxsize=1)
def provenance() -> dict:
    return json.loads(PROVENANCE_PATH.read_text())


def _smooth_step(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _rot_x(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _trunk(V: np.ndarray, T: np.ndarray, y: float) -> tuple[float, float]:
    loop = max(M.section_loops(V, T, 1, y), key=lambda lp: float(np.ptp(lp[:, 0])))
    return float(np.ptp(loop[:, 0])), float(np.ptp(loop[:, 1]))


def weights(V: np.ndarray, crotch: np.ndarray, scale: float, sx: float) -> np.ndarray:
    """How much the scan decides each vertex, in [0, 1] (see the module's step 4)."""
    rel = V - crotch
    d = np.linalg.norm(rel, axis=1)
    up = np.maximum(rel[:, 1], 0.0)
    half = MOUND_HALF_WIDTH_M * sx + MOUND_WIDENING * up
    w_x = 1.0 - _smooth_step((np.abs(rel[:, 0]) - half) / (MOUND_FALLOFF_M * sx))
    w_r = 1.0 - _smooth_step((d - CORE_RADIUS_M[0] * scale) / (CORE_RADIUS_M[1] * scale))
    w_back = _smooth_step((rel[:, 2] + BACK_LIMIT_M[0] * scale) / (BACK_LIMIT_M[1] * scale))
    w_low = _smooth_step((rel[:, 1] + LOW_LIMIT_M[0] * scale) / (LOW_LIMIT_M[1] * scale))
    return w_x * w_r * w_back * w_low


def stamp(V: np.ndarray, indices: np.ndarray) -> str:
    """A hash of the surface a fit was made on: the positions of the vertices it moves."""
    return hashlib.sha256(np.round(V[indices] / STAMP_M).astype(np.int64).tobytes()).hexdigest()


def fit(V: np.ndarray, T: np.ndarray, crotch: np.ndarray) -> OutletFit:
    """Fit the scan's pelvic outlet onto the surface ``V`` (rest pose, crotch point ``crotch``)."""
    T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
    crotch = np.asarray(crotch, dtype=np.float64)
    PV, PF, breadth, depth = patch()
    b, dpt = _trunk(V, T, float(crotch[1]) + SCALE_HEIGHT_M)
    sx, sz = b / breadth, dpt / depth
    sy = float(np.sqrt(sx * sz))
    scaled = PV * [sx, sy, sz]
    scan = ContactBody(scaled, PF, reach=0.08, require_closed=False)
    # Pitch: rotate her ring into the scan's frame rather than rebuilding the scan per angle.
    dist = np.linalg.norm(V - crotch, axis=1)
    ring = (dist > PITCH_RING_M[0]) & (dist < PITCH_RING_M[1]) & (V[:, 1] > crotch[1] - 0.02)
    rel = V[ring] - crotch
    scores = []
    for deg in PITCH_DEGREES:
        d = np.abs(scan.query(rel @ _rot_x(np.radians(deg))).distance)  # R^T applied: row @ R
        d = d[np.isfinite(d)]
        scores.append(float(np.mean(np.minimum(d, 0.03))) if d.size else np.inf)
    pitch = float(PITCH_DEGREES[int(np.argmin(scores))])
    placed = scaled @ _rot_x(np.radians(pitch)).T + crotch
    mirrored = placed.copy()
    mirrored[:, 0] = 2.0 * crotch[0] - mirrored[:, 0]
    scans = (
        ContactBody(placed, PF, reach=SEARCH_M, require_closed=False),
        ContactBody(mirrored, PF[:, ::-1], reach=SEARCH_M, require_closed=False),
    )

    # The local problem: free vertices, and two rings of fixed ones round them (3 cm is many more).
    local = np.flatnonzero(dist < FREE_RADIUS_M + 0.03)
    where = np.full(V.shape[0], -1, dtype=np.int64)
    where[local] = np.arange(local.size)
    faces = where[T[(where[T] >= 0).all(axis=1)]]
    pairs = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.unique(np.sort(pairs, 1), axis=0)
    ii = np.concatenate([edges[:, 0], edges[:, 1]])
    jj = np.concatenate([edges[:, 1], edges[:, 0]])
    deg = np.bincount(ii, minlength=local.size).astype(np.float64)
    free = dist[local] < FREE_RADIUS_M
    X0 = V[local]
    w_all = weights(X0, crotch, sy, sx)

    def L(Z):  # graph Laplacian D - A
        out = deg[:, None] * Z
        np.subtract.at(out, ii, Z[jj])
        return out

    def A(U):  # (SMOOTHNESS L D^-2 L + W) restricted to the free vertices
        Z = np.zeros_like(X0)
        Z[free] = U
        return (SMOOTHNESS * L(L(Z) / deg[:, None] ** 2) + w[:, None] * Z)[free]

    lap_diag = np.zeros(local.size)
    np.add.at(lap_diag, ii, 1.0 / deg[jj] ** 2)
    U = np.zeros((int(free.sum()), 3))
    X = X0.copy()
    residual = np.nan
    for _ in range(OUTER_ITERATIONS):
        q = [s.query(X[free]) for s in scans]
        ok = np.isfinite(q[0].distance) & np.isfinite(q[1].distance)
        ok &= (np.abs(q[0].distance) < SEARCH_M) & (np.abs(q[1].distance) < SEARCH_M)
        target = 0.5 * (q[0].closest + q[1].closest)
        w = np.zeros(local.size)
        w[np.flatnonzero(free)[ok]] = w_all[free][ok]
        rhs = (w[free][:, None] * (target - X0[free])) * ok[:, None]
        precond = 1.0 / (SMOOTHNESS * (1.0 + lap_diag[free]) + w[free])
        r = rhs - A(U)
        z = r * precond[:, None]
        p = z.copy()
        rz = float((r * z).sum())
        for _ in range(CG_ITERATIONS):
            Ap = A(p)
            alpha = rz / float((p * Ap).sum())
            U += alpha * p
            r -= alpha * Ap
            z = r * precond[:, None]
            rz_new = float((r * z).sum())
            if rz_new < 1e-20:
                break
            p = z + (rz_new / rz) * p
            rz = rz_new
        X[free] = X0[free] + U
        gap = np.linalg.norm(target - X[free], axis=1)[ok]
        residual = float(np.sum(gap * w[free][ok]) / max(np.sum(w[free][ok]), 1e-12))
    moved = np.linalg.norm(U, axis=1) > 1e-7
    indices = local[np.flatnonzero(free)[moved]]
    report = {
        "scale": [round(sx, 4), round(sy, 4), round(sz, 4)],
        "pitchDegrees": pitch,
        "ringAgreementMm": round(min(scores) * 1000, 2),
        "weightedResidualMm": round(residual * 1000, 3),
        "maxMoveMm": round(float(np.linalg.norm(U, axis=1).max()) * 1000, 1),
        "verticesMoved": int(indices.size),
        "verticesDrawn": int((w_all > 0.5).sum()),
    }
    return OutletFit(indices=indices, delta=U[moved], report=report)


@lru_cache(maxsize=1)
def stored() -> dict:
    if not OUTLET_PATH.exists():
        return {}
    data = np.load(OUTLET_PATH)
    out = {}
    for size_id in [str(s) for s in data["sizes"]]:
        out[size_id] = (
            data[f"{size_id}/indices"].astype(np.int64),
            data[f"{size_id}/delta"].astype(np.float64),
            str(data[f"{size_id}/stamp"]),
        )
    return out


def apply(size_id: str, V: np.ndarray) -> tuple[np.ndarray, str]:
    """(surface with her pelvic outlet, status): ``applied``, or why not, with the surface unchanged.

    Fails soft: a body whose stored fit is missing or was made on a different surface is returned
    as it was, with a warning naming the tool that fits it again.
    """
    entry = stored().get(size_id)
    if entry is None:
        warnings.warn(f"no pelvic outlet fitted for {size_id}: run tools/anatomy/fit_pelvis.py", stacklevel=2)
        return V, "missing"
    indices, delta, expected = entry
    if indices.size and (indices.max() >= V.shape[0] or stamp(V, indices) != expected):
        warnings.warn(
            f"the pelvic outlet for {size_id} was fitted to a different surface (recalibrated?): "
            "run tools/anatomy/fit_pelvis.py",
            stacklevel=2,
        )
        return V, "stale"
    out = V.copy()
    out[indices] += delta
    return out, "applied"


__all__ = ["OUTLET_PATH", "OutletFit", "apply", "fit", "patch", "provenance", "stamp", "stored", "weights"]
