"""Where a pattern block is placed: her bust points, the fold under the bust, sternum, waist, hips, crotch.

A haul bra spanned "underbust to bust top" where both were fractions of the
chest-to-waist distance, and cups were peaks at a fixed angle round her. That
is a bra drawn on a formula, and on a real figure the formula is wrong in
every direction at once: the peaks miss her bust points, the band crosses her
breasts instead of the fold under them, and the centre bridges straight across
instead of lying on her sternum. Nothing downstream can fix a garment placed
in the wrong place.

These are the landmarks a technical designer marks on a dress form before
draping, taken from her surface points rather than from bone ratios:

* **waist** — the narrowest section between hips and chest
* **full hip** — the widest above her crotch (below it, spread legs read as hip)
* **high hip** — halfway between them
* **bust points** — per side, the most forward point of the chest band
* **underbust fold** — below each bust point, where the front stops falling
  away and meets the ribcage
* **sternum** — the midline between the bust points, at mid-cup height
* **centre front / centre back, side seams** — per 1.5 cm row, from the outline
* **crotch** — from ``lowerBody`` (``geometry_checks.lower_body_profile``)

Every value records whether it was measured or fell back to a formula, and a
fallback adds a warning rather than failing: a flat-chested calibration body
has no bust points to find, and a VRoid rig's topology varies. A garment built
on a formula landmark is no worse than today's; one built on a measured one is
where it belongs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from wardrobe.engines.geometry_checks import torso_profile

#: Below this, the chest has no bust to speak of and the fold is placed by formula.
MIN_BUST_PROJECTION_M = 0.008
#: A bust point this close to the midline is a chest, not a bust.
MIN_APEX_OFFSET_M = 0.025
#: How far forward of the sternum between them the bust points must stand.
MIN_CLEAVAGE_M = 0.003
#: Front-depth samples are taken in slabs this tall.
SLAB_M = 0.005


@dataclass(slots=True)
class BodyLandmarks:
    forward: float
    centre_x: float
    crotch_y: float
    full_hip_y: float
    high_hip_y: float
    waist_y: float
    underbust_y: dict = field(default_factory=dict)  # side -> y of the fold under the bust
    bust_points: dict = field(default_factory=dict)  # side -> [x, y, z]
    sternum: list = field(default_factory=list)  # [x, y, z]
    bust_projection_m: float = 0.0
    centre_front: list = field(default_factory=list)  # [[y, z_front, z_back], ...]
    side_seams: list = field(default_factory=list)  # [[y, x_left, x_right], ...]
    sources: dict = field(default_factory=dict)  # landmark -> "measured" | "formula"
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> BodyLandmarks:
        return cls(**{k: data[k] for k in cls.__slots__ if k in data})

    def underbust(self) -> float:
        """One level for a band: the lower of the two folds, so it sits under both."""
        return float(min(self.underbust_y.values())) if self.underbust_y else self.waist_y

    def front_z(self, y: float) -> float:
        rows = np.asarray(self.centre_front, dtype=np.float64)
        return float(np.interp(y, rows[:, 0], rows[:, 1])) if rows.size else 0.0


def _front_depth(points: np.ndarray, x: float, y: float, forward: float, half: float = 0.012) -> float | None:
    """How far forward her surface is at (x, y): the max of z * forward in a small column."""
    slab = points[(np.abs(points[:, 0] - x) < half) & (np.abs(points[:, 1] - y) < SLAB_M)]
    return float((slab[:, 2] * forward).max()) if slab.shape[0] else None


def measure_landmarks(torso: np.ndarray, bones: dict, *, forward: float = 1.0, lower: dict | None = None,
                      armpit_y: float | None = None) -> BodyLandmarks | None:
    """Landmarks from ``torso`` — her body points without arms or head — and her bones.

    ``lower`` is the ``lowerBody`` measurement, for the crotch; ``armpit_y`` the
    measured armpit (``armpitY``), the top of the band a bust point is looked for in.
    """
    if torso is None or torso.shape[0] < 200 or "hips" not in bones:
        return None
    y_of = {name: float(np.asarray(p)[1]) for name, p in bones.items()}
    hips = y_of["hips"]
    chest = y_of.get("chest", y_of.get("spine", hips + 0.15) + 0.1)
    neck = y_of.get("neck", chest + 0.2)
    sources: dict[str, str] = {}
    warnings: list[str] = []

    if lower and lower.get("crotchY") is not None:
        crotch, sources["crotch"] = float(lower["crotchY"]), "measured"
    else:
        knee = y_of.get("leftLowerLeg", hips - 0.4)
        crotch, sources["crotch"] = hips - (hips - knee) * 0.12, "formula"
        warnings.append("crotch placed by formula: no leg measurement")

    armpit = float(armpit_y) if armpit_y is not None else chest + (neck - chest) * 0.35
    rows = torso_profile(torso, neck - 0.02, crotch)
    if rows is None:
        return None
    table = np.asarray(rows, dtype=np.float64)  # y, half-width, half-depth, cx, cz
    centre_x = float(np.median(table[:, 3]))

    # The waist is the smallest girth in the lower three quarters of hips-to-chest.
    # By width alone it was her underbust on a full figure (narrower, not smaller).
    between = table[(table[:, 0] > hips) & (table[:, 0] < chest - (chest - hips) * 0.25)]
    if between.shape[0]:
        a, b = between[:, 1], between[:, 2]
        girth = np.pi * (3 * (a + b) - np.sqrt((3 * a + b) * (a + 3 * b)))  # Ramanujan
        waist, sources["waist"] = float(between[np.argmin(girth), 0]), "measured"
    else:
        waist, sources["waist"] = hips + (chest - hips) * 0.4, "formula"
    seat = table[(table[:, 0] > crotch + 0.01) & (table[:, 0] < waist)]
    if seat.shape[0]:
        score = seat[:, 1] + 0.5 * seat[:, 2]
        full_hip, sources["fullHip"] = float(seat[np.argmax(score), 0]), "measured"
    else:
        full_hip, sources["fullHip"] = hips, "formula"
    high_hip = (waist + full_hip) * 0.5
    sources["highHip"] = sources["waist"] if sources["waist"] == sources["fullHip"] else "formula"

    # Bust points: per side, the most forward points of the chest band, off the midline.
    band_lo = waist + (armpit - waist) * 0.35
    region = torso[(torso[:, 1] > band_lo) & (torso[:, 1] < armpit)]
    bust_points: dict[str, list[float]] = {}
    underbust: dict[str, float] = {}
    projection = 0.0
    formula_fold = chest - (chest - waist) * 0.32
    for side, sign in (("left", 1.0), ("right", -1.0)):
        mine = region[(region[:, 0] - centre_x) * sign > 0.02]
        if mine.shape[0] < 30:
            continue
        depth = mine[:, 2] * forward
        top = mine[depth >= np.percentile(depth, 99)]
        apex = np.median(top, axis=0)
        # The fold: walking down from the bust point, the highest height at which
        # the front has fallen back to within 20% of the bust's projection over it.
        ys = np.arange(apex[1], apex[1] - 0.16, -SLAB_M)
        profile = [_front_depth(torso, float(apex[0]), float(y), forward) for y in ys]
        known = [(y, d) for y, d in zip(ys, profile, strict=True) if d is not None]
        if len(known) < 6:
            continue
        ribcage = min(d for y, d in known if y < apex[1] - 0.02) if any(
            y < apex[1] - 0.02 for y, _ in known) else known[-1][1]
        rise = float(apex[2] * forward) - ribcage
        projection = max(projection, rise)
        fold = next((float(y) for y, d in known if y < apex[1] and d <= ribcage + 0.2 * rise), None)
        bust_points[side] = [round(float(v), 5) for v in apex]
        measured = fold is not None and rise >= MIN_BUST_PROJECTION_M
        underbust[side] = round(fold if measured else formula_fold, 5)

    # A bust is there when it stands forward of the ribcage below it *and* of the
    # sternum between: a blocky torso's chest ring is forward of its waist too,
    # but its most forward point is its midline.
    dip = 0.0
    if len(bust_points) == 2:
        apex_y = float(np.mean([p[1] for p in bust_points.values()]))
        between_z = _front_depth(torso, centre_x, apex_y, forward, half=0.008)
        apex_z = float(np.mean([p[2] * forward for p in bust_points.values()]))
        spread = min(abs(p[0] - centre_x) for p in bust_points.values())
        dip = apex_z - between_z if between_z is not None and spread >= MIN_APEX_OFFSET_M else 0.0
    if len(bust_points) == 2 and projection >= MIN_BUST_PROJECTION_M and dip >= MIN_CLEAVAGE_M:
        sources["bustPoints"] = sources["underbust"] = "measured"
    else:
        sources["underbust"] = "formula"
        warnings.append(f"no bust to measure (projection {projection * 1000:.0f} mm, "
                        f"{dip * 1000:.0f} mm forward of the sternum): bust points and fold by formula")
        underbust = {"left": round(formula_fold, 5), "right": round(formula_fold, 5)}
        projection = 0.0
        sources["bustPoints"] = "formula"
        half = float(np.interp(chest, table[::-1, 0], table[::-1, 1]))
        z = _front_depth(torso, centre_x, chest, forward) or 0.0
        bust_points = {side: [round(centre_x + sign * half * 0.45, 5), round(chest, 5), round(z * forward, 5)]
                       for side, sign in (("left", 1.0), ("right", -1.0))}

    apex_mean = float(np.mean([p[1] for p in bust_points.values()]))
    mid_y = (apex_mean + float(np.mean(list(underbust.values())))) / 2
    sternum_z = _front_depth(torso, centre_x, mid_y, forward, half=0.008)
    sternum = [round(centre_x, 5), round(mid_y, 5), round((sternum_z or 0.0) * forward, 5)]
    sources["sternum"] = "measured" if sternum_z is not None else "formula"

    centre_front, side_seams = [], []
    for y, half_w, _hd, cx, _cz in table:
        column = torso[(np.abs(torso[:, 0] - centre_x) < 0.01) & (np.abs(torso[:, 1] - y) < 0.0075)]
        if column.shape[0]:
            signed = column[:, 2] * forward
            centre_front.append([round(float(y), 5), round(float(signed.max() * forward), 5),
                                 round(float(signed.min() * forward), 5)])
        side_seams.append([round(float(y), 5), round(float(cx + half_w), 5), round(float(cx - half_w), 5)])

    return BodyLandmarks(
        forward=forward, centre_x=round(centre_x, 5), crotch_y=round(crotch, 5),
        full_hip_y=round(full_hip, 5), high_hip_y=round(high_hip, 5), waist_y=round(waist, 5),
        underbust_y=underbust, bust_points=bust_points,
        sternum=sternum, bust_projection_m=round(projection, 5), centre_front=centre_front[::-1],
        side_seams=side_seams[::-1], sources=sources, warnings=warnings,
    )


def landmarks_for_document(document) -> BodyLandmarks | None:
    """The same measurement the fitter makes, from a VRM alone: for tools, previews and tests."""
    # Imported here: the shell imports this module, and these live beside it.
    from wardrobe.engines.geometry_checks import (
        armpit_height,
        body_points,
        lower_body_profile,
        select_region_points,
    )
    from wardrobe.engines.shell import LEG_BONES, OUTLINE_EXCLUDED_BONES
    from wardrobe.vrm.inspect import VrmSpec, inspect_document
    from wardrobe.vrm.measure import measure_body
    from wardrobe.vrm.skinning import build_bone_segments

    info = inspect_document(document)
    measurements = measure_body(document, info)
    whole = body_points(document)
    segments = build_bone_segments(info.humanoid_bones, measurements, list(info.humanoid_bones))
    if not segments:
        return None
    keep = {bone for bone in info.humanoid_bones if bone not in OUTLINE_EXCLUDED_BONES}
    torso = whole[select_region_points(whole, segments, keep)]
    legs = whole[select_region_points(whole, segments, set(LEG_BONES))]
    lower = lower_body_profile(whole, legs, measurements.bone_positions)
    forward = -1.0 if info.spec is VrmSpec.VRM0 else 1.0
    return measure_landmarks(torso, measurements.bone_positions, forward=forward, lower=lower,
                             armpit_y=armpit_height(whole, segments))


__all__ = ["BodyLandmarks", "MIN_BUST_PROJECTION_M", "landmarks_for_document", "measure_landmarks"]
