"""Is there a body under her clothes? Checked before anything is taken off.

The replacement stage was built on a fact verified for yourfriend's five VRoid
avatars: VRoid keeps the whole body under the clothes. That is a property of
those files, not of VRM. Plenty of character pipelines delete the skin a
garment hides, to save polygons; take that garment off and there is a hole
where her torso should be.

So before a slot is stripped, the body *as it would be without it* is sampled
across the regions that slot covered, band by band up the torso, and each band
must be closed: body surface in nearly every direction round her axis. A region
that is not closed is reported missing, and the caller keeps that garment on —
or, when the new outfit has to sit on the body there, refuses the job. Nothing
is ever generated to fill the gap: this checks for an authored body, it never
makes one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.engines.geometry_checks import body_points
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements

#: Directions round her axis a band is split into, and how many must hold body.
SECTORS = 16
MIN_BAND_COVERAGE = 0.75
BANDS_PER_REGION = 6
#: Points further than this from her axis are an arm or a hand, not her torso.
MAX_TORSO_RADIUS_M = 0.3


@dataclass(frozen=True)
class RegionCheck:
    present: bool
    confidence: float
    #: Coverage per band, bottom to top: 1.0 is body all the way round.
    bands: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"present": self.present, "confidence": round(self.confidence, 3),
                "bands": [round(b, 2) for b in self.bands]}


@dataclass(frozen=True)
class BodyIntegrity:
    regions: dict[str, RegionCheck]

    @property
    def complete(self) -> bool:
        return all(check.present for check in self.regions.values())

    def to_dict(self) -> dict:
        return {"complete": self.complete, "regions": {k: v.to_dict() for k, v in self.regions.items()}}


def region_heights(measurements: BodyMeasurements, region: str) -> tuple[float, float] | None:
    """The span of heights a region's check samples: where a torso garment sits on her."""
    bones = measurements.bone_positions

    def y(*names: str) -> float | None:
        for name in names:
            if name in bones:
                return float(bones[name][1])
        return None

    hips, spine = y("leftUpperLeg", "hips"), y("spine")
    chest = y("upperChest", "chest")
    if region == "upper" and spine is not None and chest is not None:
        return spine, chest
    if region == "lower" and hips is not None and spine is not None:
        # The pelvis above the hip joints: one closed shape. Below them it is
        # two legs, and the gap between them is not a hole.
        return hips + (spine - hips) * 0.1, spine
    return None


def check_body(
    document: GltfDocument,
    measurements: BodyMeasurements,
    regions: set[str],
    *,
    without: set[tuple[int, int]] | None = None,
    also_without: set[tuple[int, int]] | None = None,
    bare: bool = False,
) -> BodyIntegrity:
    """Whether the body is closed across ``regions`` once ``without`` is taken off.

    ``also_without`` are primitives that are not body either way — garments that
    stay on — and must not be mistaken for skin.
    """
    skip = set(without or ()) | set(also_without or ())
    points = body_points(document, skip=skip)
    hips = measurements.bone_positions.get("hips")
    axis_x = float(hips[0]) if hips is not None else 0.0
    axis_z = float(hips[2]) if hips is not None else 0.0

    checks: dict[str, RegionCheck] = {}
    for region in sorted(regions):
        span = region_heights(measurements, region)
        center_x, center_z = axis_x, axis_z
        radius = MAX_TORSO_RADIUS_M
        if bare:
            bones = measurements.bone_positions
            if region in {"upper", "lower"}:
                if region == "upper" and "neck" not in bones:
                    span = None
                if region == "upper" and "neck" in bones and "spine" in bones:
                    span = (float(bones["spine"][1]), float(bones["neck"][1]))
            else:
                side = "left" if region.startswith("left") else "right"
                names = ((side + "UpperLeg", side + "LowerLeg") if region.endswith("Thigh")
                         else (side + "LowerLeg", side + "Foot"))
                a, b = (bones.get(n) for n in names)
                span = None if a is None or b is None else (float(b[1]), float(a[1]))
                if span is not None:
                    center_x, center_z = float((a[0] + b[0]) / 2), float((a[2] + b[2]) / 2)
                    # Exclude the opposite leg; absence of one leg cannot be filled by the other.
                    other = bones.get(("right" if side == "left" else "left") + "LowerLeg")
                    if other is not None:
                        radius = min(radius, abs(float(a[0] - other[0])) * 0.49)
        if span is None or (bare and span[1] <= span[0]):
            checks[region] = RegionCheck(present=not bare, confidence=0.0)  # nothing to check against
            continue
        low, high = span
        dx, dz = points[:, 0] - center_x, points[:, 2] - center_z
        near = np.hypot(dx, dz) < radius
        sector = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * SECTORS).astype(int) % SECTORS
        bands = []
        for k in range(BANDS_PER_REGION):
            y0 = low + (high - low) * k / BANDS_PER_REGION
            y1 = low + (high - low) * (k + 1) / BANDS_PER_REGION
            inside = near & (points[:, 1] >= y0) & (points[:, 1] < y1)
            bands.append(len(np.unique(sector[inside])) / SECTORS)
        confidence = float(np.mean(bands)) if bands else 0.0
        present = min(bands) >= MIN_BAND_COVERAGE
        checks[region] = RegionCheck(present=present, confidence=confidence, bands=bands)
    return BodyIntegrity(regions=checks)


__all__ = ["BodyIntegrity", "RegionCheck", "check_body", "region_heights"]
