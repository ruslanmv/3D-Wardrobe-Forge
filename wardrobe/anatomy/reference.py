"""RB3–RB4. The anatomical reference bodies: the template calibrated to ANSUR II women.

A reference body is MakeHuman's anatomically modelled female template
(``wardrobe.anatomy.template``) with its own modifiers set so that, measured the way the survey
measured women (``wardrobe.anatomy.measure``), she reads her size's ANSUR II dimensions
(``assets/anatomy/reference-sizes.json``). Nothing about her shape is drawn here: the shape is
the template's anatomy, the proportions are the survey's.

* ``measure_body`` finds her landmarks on the mesh — crotch point, navel (omphalion), buttock
  point, bust points, knee — and takes every dimension at the landmark it is defined at. A
  landmark is detected from the geometry, never copied from a parameter, so a body whose
  landmark disagrees with its surface fails its test instead of passing it.
* ``calibrate`` solves the modifier values (bounded Levenberg–Marquardt on residuals scaled by
  each dimension's tolerance) and its record is stored in ``assets/anatomy/reference-bodies.json``.
  Building a body from the record is deterministic and takes about a second; calibrating takes
  minutes and is done by ``tools/anatomy/calibrate_reference.py``, not by the tests.

What these bodies do not model is stated, not silently substituted: see ``UNMODELLED``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from wardrobe.anatomy import measure as M
from wardrobe.anatomy.template import MACRO, Modifiers, body_surface, template

ROOT = Path(__file__).resolve().parents[2]
SIZES_PATH = ROOT / "assets" / "anatomy" / "reference-sizes.json"
BODIES_PATH = ROOT / "assets" / "anatomy" / "reference-bodies.json"

#: Subdivision levels of the reference surface: 7 mm median edges in the pelvis.
LEVELS = 2
#: The template shape landmark vertices are chosen on (see landmark_vertices).
LANDMARK_SHAPE = {"cup": 0.85}
#: Average body density used to turn her volume into a weight to check against ANSUR's scale reading.
BODY_DENSITY_KG_PER_L = 1.03

#: What these bodies model, what they approximate and what they do not support (AN-A6), region by
#: region. Every body's metadata, every reference VRM's extras and the validation report carry it, so
#: that no fit result implies more than was built.
ANATOMY = {
    "modelled": {
        "pelvicOutlet": "The mons pubis, the vulval outer contour as one closed mound, the genitocrural "
        "folds beside it and the start of the perineum, from the Human Reference Atlas female skin "
        "(CC BY 4.0; "
        "assets/anatomy/hra-provenance.json), fitted to her by wardrobe.anatomy.pelvis. Contact results "
        "there are reported under the region external-genital-region.",
        "creases": "Gluteal folds, inguinal creases and inframammary folds, from the template, measured "
        "(wardrobe.anatomy.creases).",
    },
    "approximated": {
        "pelvicOutlet": "One woman's surface (the Visible Human Female, frozen lying on her back) at its own "
        "resolution, about 5 mm edges: scaled to each size by trunk breadth and depth, pitched to her "
        "standing pelvis, mirrored to symmetry, and blended into the template over 14 cm. Not a "
        "population shape.",
    },
    "unsupported": {
        "externalGenitalDetail": "The labia minora, the clitoral hood, the vestibule and anything finer than "
        "the scan's edges are not built; the mound is closed, as the scan's is. MakeHuman's "
        "helper-genital proxy geometry is not imported.",
        "nippleAreola": "Not modelled beyond the template's surface. The bust point is the apex of the "
        "breast (the template vertex there, checked against detection as a local apex).",
        "softTissue": "The surface is rigid. Compression under a garment is not simulated yet (stage 7).",
    },
}
#: The older name: what is not supported. Reports and VRMs made before AN-A read it.
UNMODELLED = ANATOMY["unsupported"]

#: Parameters with no measurement of their own, and why they have the value they have.
SHAPE_PRIORS = {
    "template": "MakeHuman hm08 female young adult, average muscle (CC0); its modifiers are the only shape "
    "parameters, and each is solved against a measured dimension or held near its neutral value",
    "underbust": "held at neutral: ANSUR II has no underbust measurement. The resulting underbust girth is "
    "reported for bra work, not targeted",
    "breastLowerPole": "from the template's cup and firmness targets as calibrated to chest girth and "
    "depth; the cited nipple-to-fold distance (Al-Qattan et al. 2019, 77 mm, 53 slim women aged 20-25) is "
    "reported beside the body's, not forced",
    "pose": "MakeHuman's rest pose (arms down about 45 degrees, feet apart), not ANSUR's standing posture",
}

#: Dimensions calibrated against, and how close the body must come (mm; weight in kg).
TOLERANCE = {
    "stature": 4.0,
    "crotchheight": 5.0,
    "waistheightomphalion": 8.0,
    "buttockheight": 15.0,
    "chestheight": 10.0,
    "kneeheightmidpatella": 10.0,
    "chestcircumference": 10.0,
    "chestdepth": 6.0,
    # Across her chest at bust height, arms excluded. Without it nothing told breast projection from
    # trunk depth, and the solver reached chest depth by deepening her whole torso, belly included.
    "chestbreadth": 8.0,
    # Weaker than the survey's numbers: a literature mean from a different population (see SHAPE_PRIORS).
    "internippleDistanceMm": 25.0,
    "waistcircumference": 10.0,
    "waistdepth": 6.0,
    "waistbreadth": 6.0,
    "buttockcircumference": 10.0,
    "buttockdepth": 6.0,
    "hipbreadth": 6.0,
    "thighcircumference": 10.0,
    "lowerthighcircumference": 10.0,
    "calfcircumference": 8.0,
    "anklecircumference": 8.0,
    "crotchlengthomphalion": 12.0,
    "weightkg": 3.0,
}
#: Measured and reported beside their survey values, not calibrated to: the split of the crotch tape
#: depends on the survey's inner-thigh landmark, which a mesh cannot locate as a measurer's hand did.
REPORTED = ("crotchlengthposterioromphalion", "underbustcircumference", "nippleToInframammaryFoldMm")
#: The modifiers calibration may move, and its bounds.
FREE = {
    "weight": (0.0, 1.0),
    "height": (0.0, 1.0),
    "proportions": (0.0, 1.0),
    "cup": (0.0, 1.0),
    "firmness": (0.0, 1.0),
    "bust": (-1.0, 1.0),
    "waist": (-1.0, 1.0),
    "hips": (-1.0, 1.0),
    "thigh": (-1.0, 1.0),
    "knee": (-1.0, 1.0),
    "calf": (-1.0, 1.0),
    "ankle": (-1.0, 1.0),
    "frontchest": (-1.0, 1.0),
    "napetowaist": (-1.0, 1.0),
    "waisttohip": (-1.0, 1.0),
    "upperleg": (-1.0, 1.0),
    "lowerleg": (-1.0, 1.0),
    # Capped: pushed to +0.8 to chase buttock girth while buttock depth was already 10 mm over, it
    # left a shelf at the gluteal fold; at +0.5 the crotch length fell 3 cm short. +0.65 holds both.
    "buttocks": (-1.0, 0.65),
    "stomach": (-1.0, 1.0),
    "torsoDepth": (-1.0, 1.0),
    "hipForward": (-1.0, 1.0),
    "pelvisTone": (-1.0, 1.0),
    "breastDist": (-1.0, 1.0),
    "breastHeight": (-1.0, 1.0),
    "torsoWidth": (-1.0, 1.0),
    "hipWidth": (-1.0, 1.0),
    "hipDepth": (-1.0, 1.0),
}
#: How strongly each modifier is held to its neutral value (in squared tolerance units at full
#: travel); ``PRIOR_DEFAULT`` for the rest. No survey dimension locates her posture or the shape of
#: her belly — only depths and girths, which these can trade against each other. Weakly held, the
#: solver pushed hip translation and pelvis tone to their bounds on every size to recover waist girth
#: (the template's waist section is rounder than the survey's), and the median woman's abdomen ended
#: 2.6 cm in front of her bust point. Held firmly, the girth is missed by more and that miss is
#: reported, which is the honest trade. ``torsoDepth`` scales her whole trunk front to back; free,
#: it was how chest depth was reached, and it carried her belly forward with her bust.
PRIOR_DEFAULT = 0.05
PRIOR = {"hipForward": 4.0, "pelvisTone": 4.0, "stomach": 4.0, "torsoDepth": 4.0}


@lru_cache(maxsize=1)
def reference_sizes() -> dict:
    return json.loads(SIZES_PATH.read_text())


def targets(size_id: str) -> dict[str, float]:
    """The size's calibration targets (mm, weight kg)."""
    size = reference_sizes()["sizes"][size_id]
    d = {k: float(v) for k, v in size["dimensionsMm"].items()}
    d["internippleDistanceMm"] = float(size["breast"]["internippleDistanceMm"])
    return {k: d[k] for k in TOLERANCE}


def reported_targets(size_id: str) -> dict[str, float]:
    size = reference_sizes()["sizes"][size_id]
    return {
        "crotchlengthposterioromphalion": float(size["dimensionsMm"]["crotchlengthposterioromphalion"]),
        "nippleToInframammaryFoldMm": float(size["breast"]["nippleToInframammaryFoldMm"]),
    }


# ---------------------------------------------------------------------------------------------
# measuring the mesh
# ---------------------------------------------------------------------------------------------
@dataclass
class Measured:
    values: dict[str, float]  # mm (weight in kg)
    landmarks: dict[str, list[float]]  # metres


def _front_profile(
    sag: np.ndarray, y0: float, y1: float, step: float = 0.002
) -> tuple[np.ndarray, np.ndarray]:
    """(heights, most forward z) of a sagittal section's (z, y) points, in bins of ``step``."""
    edges = np.arange(y0, y1 + step, step)
    zs = np.full(edges.size - 1, np.nan)
    bins = np.searchsorted(edges, sag[:, 1]) - 1
    ok = (bins >= 0) & (bins < zs.size)
    best = np.full(zs.size, -np.inf)
    np.maximum.at(best, bins[ok], sag[ok, 0])
    zs[np.isfinite(best)] = best[np.isfinite(best)]
    return edges[:-1] + step / 2, zs


#: Where a bust point is looked for across her chest: lateral of the sternal margin. From 3 cm out,
#: on a body whose abdomen projected further than her breasts the search found her belly.
BUST_SEARCH_X_M = (0.05, 0.2)
#: The navel's search: profile bins, and the scale at which the abdomen is smoothed to find it.
NAVEL_STEP_M = 0.001
NAVEL_SCALE_M = 0.010


def _smooth(z: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing of a profile, with its ends held (not pulled toward zero)."""
    r = int(np.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    return np.convolve(np.pad(z, r, mode="edge"), k / k.sum(), mode="valid")


def detect_landmarks(V: np.ndarray, T: np.ndarray, joints: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Her landmarks, found on the surface by the rules a measurer follows.

    * crotch point: the lowest point of her trunk at the midline (nothing is below it between the legs);
    * omphalion: the navel, the deepest pit in her front midline profile above the hips;
    * buttock point: the most posterior point of her seat;
    * bust points: each breast's most anterior point, looked for between the spine joints that
      bracket the bust in every size (from the navel up, the search found the abdomen of a size
      whose breasts project less than her belly).
    """
    mid = M.mesh_section(V, T, 0, 0.0)[:, ::-1]  # (z, y)
    hip_y = float(joints["joint-pelvis"][1])
    knee = joints["joint-l-knee"]
    low = mid[(mid[:, 1] > float(knee[1])) & (mid[:, 1] < hip_y)]
    c = low[np.argmin(low[:, 1])]
    ys, zf = _front_profile(mid, hip_y + 0.03, hip_y + 0.25, step=NAVEL_STEP_M)
    ok = ~np.isnan(zf)
    ys, zf = ys[ok], zf[ok]
    # The navel is the deepest point of her front profile *relative to the abdomen around it*: the
    # profile minus its own smoothing at the scale of the navel. MakeHuman models it as a round pit
    # (3.7 mm deep on the median body) with a shallower fold about 2 cm above; "lowest point within
    # 3 cm either side" could not tell them apart, and the landmark vertex chosen by it sat on the
    # fold, 19 mm above the pit — every waist dimension was measured there.
    i = int(np.argmin(zf - _smooth(zf, NAVEL_SCALE_M / NAVEL_STEP_M)))
    yo = float(ys[i])
    # Her right buttock, as the survey measures on the right: both sides of a symmetric body tie, and
    # the search took whichever floating-point noise favoured — on one size the other buttock.
    seat = V[(V[:, 0] < -0.02) & (V[:, 0] > -0.14) & (V[:, 1] > c[1]) & (V[:, 1] < yo)]
    lo_y, hi_y = float(joints["joint-spine-2"][1]), float(joints["joint-spine-1"][1]) + 0.02
    out = {
        "crotch": np.array([0.0, c[1], c[0]]),
        "omphalion": np.array([0.0, yo, zf[i]]),
        "buttockPoint": seat[np.argmin(seat[:, 2])],
    }
    for name, side in (("bustPointLeft", 1.0), ("bustPointRight", -1.0)):
        box = (side * V[:, 0] > BUST_SEARCH_X_M[0]) & (side * V[:, 0] < BUST_SEARCH_X_M[1])
        box &= (V[:, 1] > lo_y) & (V[:, 1] < hi_y)
        out[name] = _apex(V, box)
    return out


#: A bust point is an apex: no point of her surface within this distance stands in front of it.
BUST_APEX_RADIUS_M = 0.02


def _apex(V: np.ndarray, box: np.ndarray) -> np.ndarray:
    """The most anterior point in ``box`` that is also a local apex of her surface.

    "Most anterior in the box" alone found, on a small-breasted body, her medial chest 5 cm below
    the nipple at the box's inner edge — a point her midline stands in front of, not the breast's
    apex. Candidates are tried from the front back; the first with nothing of her (box or not)
    further forward within ``BUST_APEX_RADIUS_M`` is the apex.
    """
    candidates = np.flatnonzero(box)
    candidates = candidates[np.argsort(-V[candidates, 2])]
    lo, hi = V[box].min(axis=0) - BUST_APEX_RADIUS_M, V[box].max(axis=0) + BUST_APEX_RADIUS_M
    near = V[np.all((lo <= V) & (hi >= V), axis=1)]
    for i in candidates[:4000]:
        d = np.linalg.norm(near - V[i], axis=1)
        if not np.any((d < BUST_APEX_RADIUS_M) & (near[:, 2] > V[i, 2] + 1e-9)):
            return V[i]
    return V[candidates[0]]


@lru_cache(maxsize=1)
def landmark_vertices() -> dict[str, int]:
    """Each landmark's template vertex, chosen once on the neutral template by ``detect_landmarks``.

    The template's topology is fixed and every target moves its vertices, so a landmark vertex
    moves with her as she is fitted to a size. Measuring through it keeps every dimension a smooth
    function of the modifiers; re-detecting at every calibration step jumped — on one trial shape
    the bust search found the abdomen — and the solver could not converge. The tests check, on
    every finished body, that detection by the rules still lands within a few millimetres of the
    vertex, so the landmarks keep corresponding to her geometry.
    """
    # Chosen on the smooth reference surface, and on a template with a distinct breast: on the
    # neutral template the chest front is nearly flat and "most anterior" slid toward the sternum.
    V, T, J = build(LANDMARK_SHAPE, LEVELS)
    detected = detect_landmarks(V, T, J)
    body = template().body_count  # the template's own vertices come first at every level
    out = {}
    for name, point in detected.items():
        d = np.linalg.norm(V[:body] - point, axis=1)
        if name in ("crotch", "omphalion"):
            d = d + 10.0 * (np.abs(V[:body, 0]) > 1e-5)  # on the midline
        out[name] = int(np.argmin(d))
    return out


def measure_body(
    V: np.ndarray, T: np.ndarray, joints: dict[str, np.ndarray], *, detect: bool = False
) -> Measured:
    """Every calibrated dimension, from the mesh, at her landmarks (template vertices, or detected).

    The subdivided surface keeps the template's vertices first, so a landmark vertex index is the
    same at every subdivision level.
    """
    out: dict[str, float] = {}

    def section(axis, value):
        return M.mesh_section(V, T, axis, value)

    def sagittal(x):
        return section(0, x)[:, ::-1]  # (z, y)

    def trunk_at(y):
        """Her trunk's section: the loop her midline passes through. The arms hang beside her in the
        rest pose and are loops of their own; taken by a box, they joined the chest girth (1391 mm)."""
        loops = M.section_loops(V, T, 1, y)
        trunk = [lp for lp in loops if np.abs(lp[:, 0]).min() < 0.02 and lp[:, 1].min() < lp[:, 1].max()]
        return np.vstack([M.resample(lp) for lp in trunk]) if trunk else np.zeros((0, 2))

    marks = detect_landmarks(V, T, joints) if detect else {k: V[i] for k, i in landmark_vertices().items()}
    lm: dict[str, list[float]] = {k: np.asarray(v, dtype=float).tolist() for k, v in marks.items()}
    H = float(V[:, 1].max())
    out["stature"] = H * 1000
    knee, ankle = joints["joint-l-knee"], joints["joint-l-ankle"]
    crotch = np.array([marks["crotch"][2], marks["crotch"][1]])  # (z, y)
    out["crotchheight"] = float(crotch[1]) * 1000
    yo = float(marks["omphalion"][1])
    out["waistheightomphalion"] = yo * 1000
    pts = trunk_at(yo)
    out["waistcircumference"] = M.girth(pts) * 1000
    out["waistdepth"] = float(np.ptp(pts[:, 1])) * 1000
    out["waistbreadth"] = float(np.ptp(pts[:, 0])) * 1000
    yb = float(marks["buttockPoint"][1])
    out["buttockheight"] = yb * 1000
    pts = trunk_at(yb)
    out["buttockcircumference"] = M.girth(pts) * 1000
    out["buttockdepth"] = float(np.ptp(pts[:, 1])) * 1000
    out["hipbreadth"] = float(np.ptp(pts[:, 0])) * 1000
    apexes = [np.asarray(marks["bustPointLeft"]), np.asarray(marks["bustPointRight"])]
    yc = float(np.mean([a[1] for a in apexes]))
    out["chestheight"] = yc * 1000
    out["internippleDistanceMm"] = float(apexes[0][0] - apexes[1][0]) * 1000
    pts = trunk_at(yc)
    out["chestcircumference"] = M.girth(pts) * 1000
    out["chestdepth"] = float(np.ptp(pts[:, 1])) * 1000
    out["chestbreadth"] = float(np.ptp(pts[:, 0])) * 1000
    # Knee: MakeHuman's knee joint sits behind the middle of the patella; its height stands for midpatella.
    out["kneeheightmidpatella"] = float(knee[1]) * 1000
    lm["knee"] = np.asarray(knee, dtype=float).tolist()

    def limb(y):
        """Her left leg's section at ``y``: the loop wholly on her left that is not an arm."""
        loops = [lp for lp in M.section_loops(V, T, 1, y) if lp[:, 0].min() > 0.0 and lp[:, 0].max() < 0.3]
        if not loops:
            return 0.0
        leg = max(loops, key=lambda lp: M.girth(lp))
        return M.girth(leg) * 1000

    out["thighcircumference"] = max(limb(float(crotch[1]) - dy) for dy in (0.01, 0.025, 0.04, 0.06, 0.08))
    out["lowerthighcircumference"] = limb(float(knee[1]) + 0.07)
    out["calfcircumference"] = max(limb(float(knee[1]) - dy) for dy in (0.06, 0.08, 0.10, 0.12, 0.14, 0.16))
    out["anklecircumference"] = min(limb(float(ankle[1]) + dy) for dy in (0.04, 0.06, 0.08, 0.10))
    front, back = tapes(sagittal, crotch, yo)
    out["crotchlengthomphalion"], out["crotchlengthposterioromphalion"] = (front + back) * 1000, back * 1000
    out["nippleToInframammaryFoldMm"] = nipple_to_fold(sagittal, apexes[0], yo) * 1000
    # Weight from volume: the surface is closed and outward-facing, so the divergence theorem is exact.
    volume = float(np.einsum("ij,ij->i", V[T[:, 0]], np.cross(V[T[:, 1]], V[T[:, 2]])).sum() / 6.0)
    out["weightkg"] = volume * 1000 * BODY_DENSITY_KG_PER_L
    # Reported, not targeted.
    out["underbustcircumference"] = M.girth(trunk_at(yc - 0.075)) * 1000
    return Measured(out, lm)


def nipple_to_fold(sagittal, apex: np.ndarray, yo: float) -> float:
    """Surface distance from the bust point down to the inframammary fold, in the bust point's plane.

    The fold is where her front profile turns sharpest from the breast's lower pole to the chest
    wall below it — a crease, found from the profile's bend, not the deepest point (the waist is
    deeper still).
    """
    if float(apex[1]) < yo + 0.03:
        return float("nan")  # no breast above the navel to measure: a trial shape, not a body
    sag = sagittal(float(apex[0]))
    ys, zf = _front_profile(sag, yo, float(apex[1]) + 0.001, step=0.002)
    ok = ~np.isnan(zf)
    ys, zf = ys[ok], zf[ok]
    if zf.size < 12:
        return float("nan")
    smooth = np.convolve(zf, np.ones(5) / 5, mode="same")
    bend = np.full(smooth.size, -np.inf)
    bend[2:-2] = smooth[4:] - 2 * smooth[2:-2] + smooth[:-4]
    bend[-6:] = -np.inf
    fold = int(np.argmax(bend))
    return float(np.hypot(np.diff(ys[fold:]), np.diff(zf[fold:])).sum())


#: How near omphalion height a hull edge must lie to be the tape's top chord, not part of it.
TAPE_EDGE_M = 0.003


def tapes(sagittal, crotch: np.ndarray, yo: float) -> tuple[float, float]:
    """(anterior, posterior) crotch tape in metres; ``sagittal(x)`` gives a plane's (z, y) points.

    Each part is the convex path from the crotch point up her front (or back) to omphalion height:
    the hull of that side's section, closed by the crotch point and the point above it at
    omphalion height, without its top chord and without the vertical edge on the crotch line.
    The top chord is recognised within ``TAPE_EDGE_M``: a section's highest row sits a little below
    omphalion height, and counting that chord once added 14 cm to the front tape.
    """
    zc, y0 = float(crotch[0]), float(crotch[1])
    out = []
    for planes, side in (((M.CROTCH_TAPE_X,), 1.0), (M.CROTCH_TAPE_BACK_X, -1.0)):
        pts = np.vstack([sagittal(x) for x in planes])
        pts = pts[(pts[:, 1] >= y0 - 0.002) & (pts[:, 1] <= yo) & ((pts[:, 0] - zc) * side >= 0)]
        poly = M.hull(np.vstack([pts, [[zc, y0], [zc, yo]]]))
        length = 0.0
        for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True):
            on_line = abs(a[0] - zc) < 1e-7 and abs(b[0] - zc) < 1e-7
            on_top = a[1] > yo - TAPE_EDGE_M and b[1] > yo - TAPE_EDGE_M
            if not (on_line or on_top):
                length += float(np.linalg.norm(b - a))
        out.append(length)
    return out[0], out[1]


# ---------------------------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------------------------
def build(values: dict[str, float], levels: int = LEVELS):
    return body_surface(Modifiers(dict(values)), levels=levels)


def neutral(name: str) -> float:
    return MACRO[name][2] if name in MACRO else 0.0


def residuals(values: dict[str, float], goal: dict[str, float], levels: int) -> np.ndarray:
    V, T, J = build(values, levels)
    try:
        got = measure_body(V, T, J).values
    except (ValueError, IndexError):
        # A trial shape whose landmarks cannot be found is as far from a body as it gets.
        return np.full(len(TOLERANCE), 1e3)
    r = np.array([(got[k] - goal[k]) / TOLERANCE[k] for k in TOLERANCE])
    return np.where(np.isfinite(r), r, 1e3)


def calibrate(
    size_id: str, *, iterations: int = 20, levels: int = 1, log=None, start: dict | None = None
) -> dict:
    """Solve the modifiers for a size. Returns the record stored in reference-bodies.json.

    Levenberg–Marquardt on residuals in units of each dimension's tolerance, so a millimetre of
    stature and a kilogram of weight count as much as their tolerances say. A pull toward each
    modifier's neutral value (``PRIOR``: weak for most, firm for posture and belly shape, which no
    measurement locates) keeps what the survey does not constrain where the template has it.
    Calibrated on one subdivision level (four times faster); the record is measured
    at the reference level, and that is what the tests hold it to.
    """
    goal = targets(size_id)
    names = list(FREE)
    lo = np.array([FREE[n][0] for n in names])
    hi = np.array([FREE[n][1] for n in names])
    centre = np.array([neutral(n) for n in names])
    x = (
        centre.copy()
        if start is None
        else np.clip(np.array([start.get(n, neutral(n)) for n in names]), lo, hi)
    )
    damping, restarts = 1.0, 1
    prior = np.diag([PRIOR.get(n, PRIOR_DEFAULT) for n in names])

    def values_of(vec):
        return dict(zip(names, map(float, vec), strict=True))

    r = residuals(values_of(x), goal, levels)
    for it in range(iterations):
        J = np.zeros((r.size, x.size))
        for j in range(x.size):
            h = 0.02 if x[j] + 0.02 <= hi[j] else -0.02
            xx = x.copy()
            xx[j] += h
            J[:, j] = (residuals(values_of(xx), goal, levels) - r) / h
        JtJ = J.T @ J
        while True:
            A = JtJ + damping * np.diag(np.diag(JtJ) + 1e-6) + prior
            step = np.linalg.solve(A, -(J.T @ r) - prior @ (x - centre))
            trial = np.clip(x + step, lo, hi)
            rt = residuals(values_of(trial), goal, levels)
            if rt @ rt < r @ r:
                x, r, damping = trial, rt, max(damping / 3, 1e-4)
                break
            damping *= 4
            if damping > 1e4:
                break
        if log:
            log(
                it,
                float(np.sqrt(np.mean(r**2))),
                {k: round(float(v * TOLERANCE[k]), 1) for k, v in zip(TOLERANCE, r, strict=True)},
            )
        if np.all(np.abs(r) < 0.5):
            break
        if damping > 1e4:
            # Stuck from this Jacobian: take a fresh one once, from where it got to, before stopping.
            if not restarts:
                break
            restarts, damping = restarts - 1, 1.0
    values = values_of(x)
    V, T, J = build(values, LEVELS)
    m = measure_body(V, T, J)
    record = {
        "modifiers": {k: round(v, 5) for k, v in values.items()},
        "measured": {k: round(v, 2) for k, v in m.values.items()},
        "targets": goal,
        "reportedTargets": reported_targets(size_id),
    }
    record["outsideTolerance"] = outside_tolerance(record)
    return record


#: A finished body is accepted when every calibrated dimension is within this many of its bound.
ACCEPT_FACTOR = 2.0


def acceptance(size_id: str) -> dict[str, float]:
    """How far each dimension may miss its target for the body to be accepted (mm; weight kg).

    A target is a regression prediction from the size's four drivers, not a measured woman: real
    women with those drivers spread around it by the regression's residual SD (11 mm for chest
    breadth, 29 mm for crotch length). The bound is ``ACCEPT_FACTOR`` times the larger of the
    dimension's tolerance and that spread — a body inside it is a plausible member of the size,
    and every miss beyond tolerance is still listed in the record. The drivers themselves have no
    spread, so they are held to their tolerances.
    """
    fit = reference_sizes()["sizes"][size_id]["fit"]
    return {
        k: ACCEPT_FACTOR * max(tol, float(fit.get(k, {}).get("residualSdMm") or 0.0))
        for k, tol in TOLERANCE.items()
    }


def outside_tolerance(record: dict) -> dict[str, float]:
    """The calibrated dimensions a record misses by more than their tolerance (measured − target)."""
    return {
        k: round(record["measured"][k] - record["targets"][k], 1)
        for k, tol in TOLERANCE.items()
        if abs(record["measured"][k] - record["targets"][k]) > tol
    }


@lru_cache(maxsize=1)
def reference_bodies() -> dict:
    return json.loads(BODIES_PATH.read_text())


def reference_body(size_id: str, *, pelvic_outlet: bool = True):
    """(vertices, triangles, joints, measured) for a size, from its recorded modifiers.

    With ``pelvic_outlet`` (AN-A2) her surface between her thighs is the atlas's, as fitted to her
    by ``tools/anatomy/fit_pelvis.py``; ``build`` alone gives the template surface the calibration
    record was measured on. Only vertices move, never the topology, so the rig's weights, the
    landmarks' vertex indices and the subdivision all still hold. A stored fit that is missing or
    was made on another surface is left out with a warning (``pelvis.apply``).
    """
    record = reference_bodies()["bodies"][size_id]
    V, T, J = build(record["modifiers"], LEVELS)
    if pelvic_outlet:
        from wardrobe.anatomy import pelvis  # it imports contact, which imports measure only

        V, _ = pelvis.apply(size_id, V)
    return V, T, J, measure_body(V, T, J)


__all__ = [
    "BODIES_PATH",
    "FREE",
    "detect_landmarks",
    "landmark_vertices",
    "LEVELS",
    "Measured",
    "REPORTED",
    "SHAPE_PRIORS",
    "TOLERANCE",
    "UNMODELLED",
    "build",
    "calibrate",
    "measure_body",
    "nipple_to_fold",
    "outside_tolerance",
    "reference_bodies",
    "reference_body",
    "reference_sizes",
    "reported_targets",
    "targets",
    "tapes",
]
