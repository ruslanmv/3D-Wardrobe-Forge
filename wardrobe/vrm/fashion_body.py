"""Fashion-fit forms: adult-proportioned, smooth, faceless bodies to judge close-fitting garments on.

The calibration bodies in ``wardrobe.vrm.build`` are deliberately crude — five
elliptical rings for a torso, cylinders for legs, no feet — because they exist
to vary proportion, not shape. That is exactly what makes them useless for
lingerie: a bra on a torso with no bust has nothing to shape round, briefs on a
capped tube have no crotch to cross, a stocking foot has no foot, and a hip
ring's hard corner shows through every bodycon dress as a ridge. The review
that started this work (looks #2–#11 all "passed" and all looked wrong) could
not have been done on them.

A fit form is what a technical designer's dress form is: a smooth surface at a
declared size, measured the way a tape measures (the convex girth at bust,
underbust, waist, high hip and full hip), with broad, low-frequency bust and
seat volume and nothing else. It is generated here, from numbers, so it
carries no third-party licence and depicts no one. It has no anatomical
detail by construction: every shape term is a Gaussian at least several
centimetres across, and ``tests/unit/test_fashion_form.py`` holds that to a
curvature bound.

The forms are declared adult in ``assets/calibration/policy.json`` like the
calibration bodies, by the repository and not by anything in a request, and
go through the same gate as any avatar. They are **not** in
``CALIBRATION_BODIES``: four test modules and the gallery's hash baseline
iterate that tuple, and adding to it would move all of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate
from wardrobe.vrm.build import BodyProportions, build_vrm, skeleton_positions

#: Rings up the torso, legs and feet are this far apart at most.
RING_STEP_M = 0.012
TORSO_SEGMENTS = 48
LIMB_SEGMENTS = 32
#: Superellipse exponent of a torso section: 2 is an ellipse, higher is squarer. A body is between.
SECTION_EXPONENT = 2.3


@dataclass(slots=True)
class FitFormProportions(BodyProportions):
    """A size chart, in metres, as a tape measures: girths are the convex perimeter at that height."""

    bust_girth: float = 0.88
    underbust_girth: float = 0.75
    waist_girth: float = 0.70
    high_hip_girth: float = 0.86
    full_hip_girth: float = 0.96
    thigh_girth: float = 0.56
    knee_girth: float = 0.36
    calf_girth: float = 0.35
    ankle_girth: float = 0.22
    neck_girth: float = 0.33
    upper_arm_girth: float = 0.27
    wrist_girth: float = 0.155
    #: How far the bust stands forward of the ribcage, before the girth is fitted to the chart.
    bust_projection: float = 0.035
    #: Apex to apex.
    bust_span: float = 0.18
    seat_projection: float = 0.03
    foot_length: float = 0.24


#: Two sizes a lingerie block has to hold on: a misses 38 / 75B and a curvy 44 / 85D.
FASHION_FIT_BODIES: tuple[FitFormProportions, ...] = (
    FitFormProportions(
        name="fit-form-a-misses", height=1.68, shoulder_width=0.35, hip_width=0.34, chest_width=0.32,
        depth=0.23, leg_ratio=0.52, arm_ratio=0.44,
        bust_girth=0.88, underbust_girth=0.75, waist_girth=0.70, high_hip_girth=0.86, full_hip_girth=0.96,
        thigh_girth=0.56, knee_girth=0.36, calf_girth=0.35, ankle_girth=0.22, neck_girth=0.33,
        upper_arm_girth=0.27, wrist_girth=0.155, bust_projection=0.035, bust_span=0.18,
        seat_projection=0.03, foot_length=0.24,
    ),
    FitFormProportions(
        name="fit-form-b-curvy", height=1.66, shoulder_width=0.37, hip_width=0.40, chest_width=0.36,
        depth=0.27, leg_ratio=0.51, arm_ratio=0.44,
        bust_girth=1.04, underbust_girth=0.85, waist_girth=0.84, high_hip_girth=1.00, full_hip_girth=1.12,
        thigh_girth=0.66, knee_girth=0.40, calf_girth=0.39, ankle_girth=0.235, neck_girth=0.35,
        upper_arm_girth=0.31, wrist_girth=0.165, bust_projection=0.055, bust_span=0.20,
        seat_projection=0.04, foot_length=0.245,
    ),
)


def form_landmarks(form: FitFormProportions, positions: dict[str, np.ndarray]) -> dict[str, float]:
    """The heights the chart is declared at, from the skeleton, as a dress form's maker marks them."""
    h = form.height
    hips = float(positions["hips"][1])
    neck = float(positions["neck"][1])
    span = neck - hips
    upper_leg = float(positions["leftUpperLeg"][1])
    waist = hips + span * 0.30
    full_hip = upper_leg + h * 0.01
    return {
        "crotch": upper_leg - h * 0.035,
        "fullHip": full_hip,
        "highHip": (waist + full_hip) * 0.5,
        "waist": waist,
        "underbust": hips + span * 0.57,
        "bust": hips + span * 0.655,
        "armpit": hips + span * 0.80,
        "shoulder": float(positions["leftUpperArm"][1]),
        "neck": neck,
    }


# ----------------------------------------------------------------------
# sections
# ----------------------------------------------------------------------
def _superellipse(angles: np.ndarray, a: float, b: float, n: float = SECTION_EXPONENT) -> np.ndarray:
    s, c = np.sin(angles), np.cos(angles)
    x = a * np.sign(s) * np.abs(s) ** (2.0 / n)
    z = b * np.sign(c) * np.abs(c) ** (2.0 / n)
    return np.stack([x, z], axis=1)


def _stadium(angles: np.ndarray, half_width: float, radius: float) -> np.ndarray:
    """The hull of two circles side by side (a pair of thighs from above), sampled by ray from the middle.

    Each angle's point is where a ray from the centre meets the outline, so it is
    comparable, angle for angle, with a torso section it is blended into.
    """
    s, c = np.sin(angles), np.cos(angles)
    centre = max(half_width - radius, 0.0)
    out = np.empty((angles.size, 2))
    for k, (dx, dz) in enumerate(zip(s, c, strict=True)):
        t_flat = radius / abs(dz) if abs(dz) > 1e-9 else np.inf
        if abs(dx * t_flat) <= centre:
            t = t_flat
        else:
            cx = centre if dx >= 0 else -centre
            dot = dx * cx
            t = dot + math.sqrt(max(dot * dot - cx * cx + radius * radius, 0.0))
        out[k] = (dx * t, dz * t)
    return out


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def convex_girth(xz: np.ndarray) -> float:
    """The perimeter of the convex hull of a section: what a tape measure reads round it."""
    points = np.unique(np.round(np.asarray(xz, dtype=np.float64), 7), axis=0)
    if points.shape[0] < 3:
        return 0.0
    points = points[np.lexsort((points[:, 1], points[:, 0]))]

    def half(sequence):
        hull: list[np.ndarray] = []
        for p in sequence:
            while len(hull) >= 2 and _cross(hull[-1] - hull[-2], p - hull[-2]) <= 0:
                hull.pop()
            hull.append(p)
        return hull

    lower, upper = half(points), half(points[::-1])
    hull = np.array(lower[:-1] + upper[:-1])
    return float(np.linalg.norm(np.diff(np.vstack([hull, hull[:1]]), axis=0), axis=1).sum())


def _pchip(x: float, xs: list[float], ys: list[float]) -> float:
    """Monotone cubic (Fritsch–Carlson) through the chart: no kink at a landmark, no overshoot between."""
    xs_a, ys_a = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    if x <= xs_a[0]:
        return float(ys_a[0])
    if x >= xs_a[-1]:
        return float(ys_a[-1])
    h = np.diff(xs_a)
    delta = np.diff(ys_a) / h
    m = np.zeros_like(ys_a)
    m[0], m[-1] = delta[0], delta[-1]
    for k in range(1, len(xs_a) - 1):
        if delta[k - 1] * delta[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
    k = int(np.searchsorted(xs_a, x) - 1)
    t = (x - xs_a[k]) / h[k]
    h00, h10 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t
    h01, h11 = -2 * t**3 + 3 * t**2, t**3 - t**2
    return float(h00 * ys_a[k] + h10 * h[k] * m[k] + h01 * ys_a[k + 1] + h11 * h[k] * m[k + 1])


def _gauss(value, centre: float, sigma: float):
    return np.exp(-0.5 * ((value - centre) / sigma) ** 2)


def _torso_sections(form: FitFormProportions, marks: dict[str, float], forward: float
                    ) -> tuple[list[float], list[np.ndarray]]:
    """(heights, sections): each section is (segments+1, 2) x/z points, seam duplicated at her back."""
    h = form.height
    angles = math.pi + np.linspace(0.0, 2.0 * math.pi, TORSO_SEGMENTS + 1)  # start at her back
    half_shoulder = form.shoulder_width * 0.5
    arm_r = form.upper_arm_girth / (2 * math.pi)
    neck_r = form.neck_girth / (2 * math.pi)

    # Girth-calibrated controls: (height, girth, depth / width).
    chest = (form.bust_girth + form.underbust_girth) * 0.5 * 1.02
    girths = [
        (marks["crotch"], form.full_hip_girth * 0.93, 0.78),
        (marks["fullHip"], form.full_hip_girth, 0.74),
        (marks["highHip"], form.high_hip_girth, 0.70),
        (marks["waist"], form.waist_girth, 0.72),
        (marks["underbust"], form.underbust_girth, 0.74),
        (marks["bust"], form.bust_girth, 0.72),
        (marks["armpit"], chest, 0.66),
    ]
    # Above the armpit the chart has no girth: the shoulders are shaped to the skeleton.
    shaped = [
        (marks["shoulder"], half_shoulder + arm_r * 0.8, 0.062 * h / 1.68),
        (marks["shoulder"] + 0.02 * h, half_shoulder * 0.72, 0.056 * h / 1.68),
        (marks["neck"], neck_r * 1.02, neck_r * 0.95),
        (marks["neck"] + 0.055 * h, neck_r, neck_r * 0.92),
    ]
    heights = np.arange(girths[0][0], shaped[-1][0] + 1e-9, RING_STEP_M).tolist()
    ys_g = [g[0] for g in girths]
    ys_s = [marks["armpit"]] + [s[0] for s in shaped]

    bust_y, seat_y = marks["bust"] - 0.004, marks["fullHip"] + 0.012
    thigh_x = form.hip_width * 0.27  # the thigh joints' spacing, as skeleton_positions places them
    thigh_r = form.thigh_girth / (2 * math.pi)
    sigma_x_bust = form.bust_span * 0.2  # broad enough to carry no detail, narrow enough to keep the span
    sections = []
    armpit_a = armpit_b = None
    for y in heights:
        if y <= marks["armpit"] + 1e-9:
            girth = float(_pchip(y, ys_g, [g[1] for g in girths]))
            ratio = float(np.interp(y, ys_g, [g[2] for g in girths]))
            base = _superellipse(angles, 1.0, ratio)
            # Bust: two broad mounds forward of the ribcage. The fold under the bust
            # is sharper than the slope above it, as on a dress form.
            sigma_y = np.where(y < bust_y, 0.028, 0.06) * h / 1.68
            rise = float(_gauss(y, bust_y, float(sigma_y)))
            front = np.clip(base[:, 1] / ratio, 0.0, 1.0)
            mounds = _gauss(base[:, 0], form.bust_span / 2 / 0.16, sigma_x_bust / 0.16) + \
                _gauss(base[:, 0], -form.bust_span / 2 / 0.16, sigma_x_bust / 0.16)
            base[:, 1] += (form.bust_projection / 0.16) * rise * mounds * front
            # Seat: the same, behind and lower.
            fall = float(_gauss(y, seat_y, 0.07 * h / 1.68))
            back = np.clip(-base[:, 1] / ratio, 0.0, 1.0)
            cheeks = (_gauss(base[:, 0], 0.055 / 0.16, 0.07 / 0.16)
                      + _gauss(base[:, 0], -0.055 / 0.16, 0.07 / 0.16))
            base[:, 1] -= (form.seat_projection / 0.16) * fall * np.minimum(cheeks, 1.0) * back
            # Scale the whole section so a tape round it reads the chart.
            section = base * (girth / convex_girth(base))
            if y < marks["fullHip"]:
                # Below the full hip the trunk becomes two thighs: blend the section
                # toward the hull of the thigh tops, so the torso does not end in a
                # box edge over her legs (the calibration body's "shorts" ledge).
                # Done 3 cm above the crotch, so the trunk meets the thighs running
                # straight down: arriving at an angle, it shaded as a line round them.
                t = (marks["fullHip"] - y) / max(marks["fullHip"] - marks["crotch"] - 0.03, 1e-6)
                w = float(np.clip(t, 0.0, 1.0)) ** 1.5
                w = w * w * (3 - 2 * w)
                pair = _stadium(angles, thigh_x + thigh_r + 0.001, thigh_r + 0.001)
                # Between the thighs the front and back recede toward the crotch in a V,
                # as the groin does, instead of a flat web turning under in a line.
                v = float(np.clip((marks["crotch"] + 0.05 - y) / 0.05, 0.0, 1.0))
                medial = np.clip(1.0 - np.abs(pair[:, 0]) / thigh_x, 0.0, 1.0)
                pair[:, 1] *= 1.0 - 0.75 * v * medial ** 1.5
                section = section * (1 - w) + pair * w
            armpit_a = float(np.ptp(section[:, 0]) / 2)
            armpit_b = float(np.ptp(section[:, 1]) / 2)
        else:
            widths = [armpit_a] + [s[1] for s in shaped]
            depths = [armpit_b] + [s[2] for s in shaped]
            a = float(np.interp(y, ys_s, widths))
            b = float(np.interp(y, ys_s, depths))
            section = _superellipse(angles, a, b, 2.6 if y < marks["neck"] else 2.0)
        section[:, 1] *= forward
        sections.append(section)
    smoothed = _smooth_sections(sections)
    # The running mean pulls the bust in and the underbust out by a centimetre or
    # two; put every charted section back to its girth, now that its shape is smooth.
    for k, y in enumerate(heights):
        # Below the full hip the section is becoming a pair of thighs: left as blended.
        if marks["fullHip"] - 1e-9 <= y <= marks["armpit"] + 1e-9:
            target = float(_pchip(y, ys_g, [g[1] for g in girths]))
            smoothed[k] = smoothed[k] * (target / convex_girth(smoothed[k]))
    return heights, smoothed


def _smooth_sections(sections: list[np.ndarray], passes: int = 2) -> list[np.ndarray]:
    """A light running mean up the torso, so the chart's landmarks do not show as creases."""
    stack = np.stack(sections)
    for _ in range(passes):
        inner = (stack[:-2] + 2 * stack[1:-1] + stack[2:]) / 4
        stack = np.concatenate([stack[:1], inner, stack[-1:]])
    return list(stack)


def _grid(rings: np.ndarray, *, name: str, cap_bottom: np.ndarray | None = None,
          cap_top: np.ndarray | None = None) -> Mesh:
    """A tube through ``rings`` (R, S+1, 3), bottom to top, seam duplicated; optional fan caps."""
    count, ring = rings.shape[0], rings.shape[1]
    segments = ring - 1
    positions = rings.reshape(-1, 3)
    faces = []
    for row in range(count - 1):
        base, above = row * ring, (row + 1) * ring
        for column in range(segments):
            a, b, c, d = base + column, base + column + 1, above + column + 1, above + column
            faces += [(a, b, c), (a, c, d)]
    extra = []
    if cap_bottom is not None:
        centre = positions.shape[0] + len(extra)
        extra.append(cap_bottom)
        faces += [(centre, column + 1, column) for column in range(segments)]
    if cap_top is not None:
        centre = positions.shape[0] + len(extra)
        extra.append(cap_top)
        top = (count - 1) * ring
        faces += [(centre, top + column, top + column + 1) for column in range(segments)]
    if extra:
        positions = np.vstack([positions, np.array(extra)])
    uvs = np.zeros((positions.shape[0], 2), dtype=np.float32)
    mesh = Mesh(positions=positions.astype(np.float32), indices=np.array(faces, dtype=np.uint32).reshape(-1),
                uvs=uvs, metadata={"section": name})
    return mesh.compute_normals()


def _torso(form: FitFormProportions, marks: dict[str, float], forward: float) -> Mesh:
    heights, sections = _torso_sections(form, marks, forward)
    rings = [np.column_stack([s[:, 0], np.full(s.shape[0], y), s[:, 1]]) for y, s in zip(heights, sections,
                                                                                            strict=True)]
    # A smooth, closed underside at the crotch: the lowest section drawn in on itself,
    # so a gusset has a surface to cross and nothing is modelled there but a curve.
    # The trunk carries on a few centimetres below the crotch just inside the thighs,
    # the web between them receding to nothing, and only then closes. Turned under at
    # the crotch itself, the last rows' normals tipped downward and shaded as a dark
    # hem line round her, like the calibration body's shorts.
    angles = math.pi + np.linspace(0.0, 2.0 * math.pi, TORSO_SEGMENTS + 1)
    thigh_x = form.hip_width * 0.27
    thigh_r = form.thigh_girth / (2 * math.pi)
    below = []
    for k, depth in enumerate((0.01, 0.02, 0.03), start=1):
        pair = _stadium(angles, thigh_x + thigh_r - 0.0015 * k, thigh_r - 0.0015 * k)
        medial = np.clip(1.0 - np.abs(pair[:, 0]) / thigh_x, 0.0, 1.0)
        pair[:, 1] *= 1.0 - (0.75 + 0.07 * k) * medial ** 1.5
        pair[:, 1] *= forward
        below.append(np.column_stack([pair[:, 0], np.full(pair.shape[0], heights[0] - depth), pair[:, 1]]))
    stack = np.stack(below[::-1] + rings)
    centre = np.array([0.0, heights[0] - 0.032, 0.0])
    return _grid(stack, name="torso", cap_bottom=centre)


def _tube(points: np.ndarray, radii: np.ndarray, *, name: str, segments: int = LIMB_SEGMENTS,
          cap_end: bool = False) -> Mesh:
    """A round tube along a path, one ring per point."""
    tangents = np.gradient(points, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
    angles = np.linspace(0.0, 2 * math.pi, segments + 1)
    rings = []
    for point, tangent, radius in zip(points, tangents, radii, strict=True):
        helper = np.array([0.0, 0.0, 1.0]) if abs(tangent[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(tangent, helper)
        u /= np.linalg.norm(u)
        v = np.cross(tangent, u)
        rings.append(point + radius * (np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v)))
    tip = points[-1] + tangents[-1] * radii[-1] * 0.6 if cap_end else None
    return _grid(np.stack(rings), name=name, cap_top=tip)


def _path(stations: list[tuple[np.ndarray, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Resample (point, radius) stations every RING_STEP_M along the polyline, radius smoothly."""
    points = np.array([p for p, _ in stations], dtype=np.float64)
    radii = np.array([r for _, r in stations], dtype=np.float64)
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    samples = np.linspace(0.0, along[-1], max(int(along[-1] / RING_STEP_M), 2) + 1)
    out = np.column_stack([np.interp(samples, along, points[:, k]) for k in range(3)])
    # Cosine-eased radius between stations: no kink at the knee or the calf.
    index = np.clip(np.searchsorted(along, samples, side="right") - 1, 0, len(along) - 2)
    t = (samples - along[index]) / np.maximum(along[index + 1] - along[index], 1e-9)
    t = 0.5 - 0.5 * np.cos(np.pi * t)
    return out, radii[index] + (radii[index + 1] - radii[index]) * t


def _leg(form: FitFormProportions, marks: dict[str, float], positions: dict, side: str) -> Mesh:
    hip, knee, foot = (np.asarray(positions[f"{side}{b}"], dtype=np.float64)
                       for b in ("UpperLeg", "LowerLeg", "Foot"))
    r = {k: getattr(form, f"{k}_girth") / (2 * math.pi) for k in ("thigh", "knee", "calf", "ankle")}

    def at(y: float) -> np.ndarray:
        if y >= knee[1]:
            t = (hip[1] - y) / (hip[1] - knee[1])
            return hip + (knee - hip) * t
        t = (knee[1] - y) / (knee[1] - foot[1])
        return knee + (foot - knee) * t

    top = marks["crotch"] + 0.02  # inside the trunk, which meets the thigh at the thigh's own size
    calf_y = knee[1] - (knee[1] - foot[1]) * 0.3
    stations = [
        (at(top), r["thigh"] * 0.9),
        (at(marks["crotch"]), r["thigh"] * 0.995),
        (at(marks["crotch"] - 0.02), r["thigh"]),
        (at(marks["crotch"] - (marks["crotch"] - knee[1]) * 0.45), r["thigh"] * 0.86),
        (at(knee[1] + 0.06), r["knee"] * 1.05),
        (at(knee[1]), r["knee"]),
        (at(calf_y), r["calf"]),
        (at(foot[1] + 0.10), r["ankle"] * 1.12),
        (at(foot[1] + 0.02), r["ankle"]),
    ]
    points, radii = _path(stations)
    return _tube(points, radii, name=f"leg-{side}")


def _foot(form: FitFormProportions, positions: dict, side: str, forward: float) -> Mesh:
    """A foot: heel to toe, oval sections standing on the floor (y = 0)."""
    h = form.height
    ankle = np.asarray(positions[f"{side}Foot"], dtype=np.float64)
    length = form.foot_length
    s = h / 1.68
    # Along the foot, heel (t=0) to toe (t=1): (t, half-width, half-height).
    profile = [(0.0, 0.022, 0.028), (0.08, 0.029, 0.038), (0.25, 0.033, 0.045), (0.5, 0.040, 0.036),
               (0.72, 0.044, 0.026), (0.9, 0.040, 0.018), (1.0, 0.030, 0.012)]
    ts = np.linspace(0.0, 1.0, max(int(length / RING_STEP_M), 8) + 1)
    widths = np.interp(ts, [p[0] for p in profile], [p[1] for p in profile]) * s
    halves = np.interp(ts, [p[0] for p in profile], [p[2] for p in profile]) * s
    angles = np.linspace(0.0, 2 * math.pi, LIMB_SEGMENTS + 1)
    rings = []
    for t, a, b in zip(ts, widths, halves, strict=True):
        z = ankle[2] + forward * (t - 0.22) * length
        # Toes turn slightly out, as they do.
        x = ankle[0] + np.sign(ankle[0]) * t * 0.012
        rings.append(np.column_stack([x + a * np.sin(angles), b + b * np.cos(angles),
                                      np.full(angles.size, z)]))
    stack = np.stack(rings)
    heel = stack[0].mean(axis=0) - np.array([0.0, 0.0, forward * 0.008])
    toe = stack[-1].mean(axis=0) + np.array([0.0, 0.0, forward * 0.006])
    return _grid(stack, name=f"foot-{side}", cap_bottom=heel, cap_top=toe)


def _arm(form: FitFormProportions, positions: dict, side: str) -> Mesh:
    shoulder, elbow, wrist = (np.asarray(positions[f"{side}{b}"], dtype=np.float64)
                              for b in ("UpperArm", "LowerArm", "Hand"))
    upper = form.upper_arm_girth / (2 * math.pi)
    lower = form.wrist_girth / (2 * math.pi)
    direction = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    # The arm starts inside her shoulder and thin, so it grows out of it rather than
    # standing on it: posed down into an A, a full-width first ring showed as a cap.
    start = shoulder - direction * upper * 0.35
    stations = [(start, upper * 0.9), (shoulder + (elbow - shoulder) * 0.12, upper * 0.98),
                (shoulder + (elbow - shoulder) * 0.3, upper),
                (elbow, (upper + lower) * 0.52), (elbow + (wrist - elbow) * 0.3, lower * 1.3),
                (wrist, lower), (wrist + direction * form.height * 0.05, lower * 1.15),
                (wrist + direction * form.height * 0.1, lower * 0.8)]
    points, radii = _path(stations)
    return _tube(points, radii, name=f"arm-{side}", cap_end=True)


def _head(form: FitFormProportions, marks: dict[str, float], forward: float) -> Mesh:
    """A smooth ovoid, no features, its crown exactly at her height."""
    h = form.height
    radius = h * 0.068
    centre_y = h - radius * 1.12
    angles = np.linspace(0.0, 2 * math.pi, TORSO_SEGMENTS + 1)
    rows = np.linspace(-0.92, 0.92, 15)
    rings = []
    for k in rows:
        y = centre_y + k * radius * 1.12
        r = radius * math.sqrt(max(1.0 - k * k, 0.0)) * (1.0 - 0.1 * max(-k, 0.0))
        rings.append(np.column_stack([r * 0.88 * np.sin(angles), np.full(angles.size, y),
                                      forward * 0.008 + r * np.cos(angles)]))
    stack = np.stack(rings)
    return _grid(stack, name="head", cap_bottom=np.array([0.0, centre_y - radius * 1.12, forward * 0.008]),
                 cap_top=np.array([0.0, h, forward * 0.008]))


def build_fit_form_mesh(form: BodyProportions, positions: dict[str, np.ndarray]) -> Mesh:
    """The form's surface in world space, facing +Z (VRM 1.0), sole at y=0, crown at its height."""
    if not isinstance(form, FitFormProportions):
        raise TypeError("a fit form is built from FitFormProportions")
    forward = 1.0
    marks = form_landmarks(form, positions)
    sections = [_torso(form, marks, forward), _head(form, marks, forward)]
    for side in ("left", "right"):
        sections += [_leg(form, marks, positions, side), _foot(form, positions, side, forward),
                     _arm(form, positions, side)]
    mesh = concatenate(sections)
    # The torso never follows an arm bone (see build_vrm): the arm is its own tube,
    # grown out of the shoulder, and rotates without tearing the chest.
    torso = np.zeros(mesh.vertex_count, dtype=bool)
    torso[: sections[0].vertex_count] = True
    mesh.metadata["bindTorso"] = torso
    return mesh


def build_fit_form(form: FitFormProportions, *, spec: str = "VRM1") -> bytes:
    """A complete, skinned VRM of the form."""
    return build_vrm(form, spec=spec, mesh_builder=build_fit_form_mesh)


def fit_form(name: str) -> FitFormProportions:
    for form in FASHION_FIT_BODIES:
        if form.name == name:
            return form
    raise KeyError(name)


def chart(form: FitFormProportions) -> dict[str, float]:
    """The declared girths, by landmark name."""
    return {"bust": form.bust_girth, "underbust": form.underbust_girth, "waist": form.waist_girth,
            "highHip": form.high_hip_girth, "fullHip": form.full_hip_girth}


def positions_for(form: FitFormProportions) -> dict[str, np.ndarray]:
    return skeleton_positions(form)


__all__ = [
    "FASHION_FIT_BODIES",
    "FitFormProportions",
    "build_fit_form",
    "build_fit_form_mesh",
    "chart",
    "convex_girth",
    "fit_form",
    "form_landmarks",
    "positions_for",
]
