"""Body measurement from a VRM's rest pose.

Measurements are derived from humanoid bone world positions plus the rest-pose
bounding box. Bone-derived values (widths between paired bones, limb lengths)
are reliable; girth-like values (chest/waist circumference) are estimated and
reported with an explicit confidence so downstream stages can decide how much
to trust them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import VrmInfo


@dataclass(slots=True)
class BodyMeasurements:
    """All lengths in metres, in the avatar's own rest-pose space."""

    height_m: float
    shoulder_width_m: float
    chest_width_m: float
    waist_width_m: float
    hip_width_m: float
    arm_length_m: float
    leg_length_m: float
    inseam_m: float
    depth_m: float

    #: World-space position of every humanoid bone we resolved.
    bone_positions: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    #: Rest-pose bounding box as ((minx,miny,minz),(maxx,maxy,maxz)).
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    #: Per-field confidence in [0,1]; 1.0 means measured directly from bones.
    confidence: dict[str, float] = field(default_factory=dict)

    @property
    def up_axis_height(self) -> float:
        return self.height_m

    def scale_relative_to(self, reference: BodyMeasurements) -> dict[str, float]:
        """Per-axis scale factors that map ``reference`` onto this body."""

        def ratio(a: float, b: float) -> float:
            return float(a / b) if b > 1e-6 else 1.0

        return {
            "height": ratio(self.height_m, reference.height_m),
            "shoulder": ratio(self.shoulder_width_m, reference.shoulder_width_m),
            "chest": ratio(self.chest_width_m, reference.chest_width_m),
            "waist": ratio(self.waist_width_m, reference.waist_width_m),
            "hip": ratio(self.hip_width_m, reference.hip_width_m),
            "leg": ratio(self.leg_length_m, reference.leg_length_m),
        }

    def to_dict(self) -> dict:
        return {
            "heightM": round(self.height_m, 4),
            "shoulderWidthM": round(self.shoulder_width_m, 4),
            "chestWidthM": round(self.chest_width_m, 4),
            "waistWidthM": round(self.waist_width_m, 4),
            "hipWidthM": round(self.hip_width_m, 4),
            "armLengthM": round(self.arm_length_m, 4),
            "legLengthM": round(self.leg_length_m, 4),
            "inseamM": round(self.inseam_m, 4),
            "depthM": round(self.depth_m, 4),
            "bonePositions": {k: [round(c, 4) for c in v] for k, v in sorted(self.bone_positions.items())},
            "bounds": (
                [[round(c, 4) for c in self.bounds[0]], [round(c, 4) for c in self.bounds[1]]]
                if self.bounds
                else None
            ),
            "confidence": {k: round(v, 2) for k, v in sorted(self.confidence.items())},
        }


class MeasurementError(ValueError):
    """The rig could not be measured (usually a degenerate or non-humanoid rig)."""


def measure_body(document: GltfDocument, info: VrmInfo) -> BodyMeasurements:
    world = document.world_matrices()
    node_count = len(document.nodes)

    positions: dict[str, np.ndarray] = {}
    for bone, node in info.humanoid_bones.items():
        if 0 <= node < node_count:
            positions[bone] = world[node][:3, 3].astype(float)

    if "hips" not in positions:
        raise MeasurementError("cannot measure a rig without a 'hips' bone")

    bounds = document.primitive_bounds()
    confidence: dict[str, float] = {}

    # --- height -------------------------------------------------------
    if bounds is not None:
        lo, hi = bounds
        height = float(hi[1] - lo[1])
        confidence["height"] = 0.9
    else:
        head = positions.get("head", positions["hips"])
        height = float(head[1]) * 1.13  # head bone sits ~88% up a humanoid figure
        confidence["height"] = 0.5
    if height <= 1e-4:
        raise MeasurementError("model has zero height; the rig or units are degenerate")

    depth = float(bounds[1][2] - bounds[0][2]) if bounds is not None else height * 0.16

    # --- widths measured directly between paired bones ----------------
    shoulder = _paired_distance(positions, "leftUpperArm", "rightUpperArm")
    if shoulder is not None:
        confidence["shoulder"] = 1.0
    else:
        shoulder = height * 0.235
        confidence["shoulder"] = 0.4

    hip = _paired_distance(positions, "leftUpperLeg", "rightUpperLeg")
    if hip is not None:
        # Upper-leg bones sit inboard of the silhouette; widen to the surface.
        hip *= 1.85
        confidence["hip"] = 0.85
    else:
        hip = height * 0.19
        confidence["hip"] = 0.4

    # --- estimated girth-like widths ----------------------------------
    chest_ref = _first(positions, "upperChest", "chest", "spine")
    if chest_ref is not None and shoulder:
        chest = shoulder * 0.88
        confidence["chest"] = 0.6
    else:
        chest = height * 0.20
        confidence["chest"] = 0.35

    waist = (chest + hip) * 0.5 * 0.86
    confidence["waist"] = 0.5

    # --- limb lengths -------------------------------------------------
    arm = _chain_length(positions, ["leftUpperArm", "leftLowerArm", "leftHand"])
    if arm is None:
        arm = _chain_length(positions, ["rightUpperArm", "rightLowerArm", "rightHand"])
    confidence["arm"] = 1.0 if arm is not None else 0.3
    arm = arm if arm is not None else height * 0.44

    leg = _chain_length(positions, ["leftUpperLeg", "leftLowerLeg", "leftFoot"])
    if leg is None:
        leg = _chain_length(positions, ["rightUpperLeg", "rightLowerLeg", "rightFoot"])
    confidence["leg"] = 1.0 if leg is not None else 0.3
    leg = leg if leg is not None else height * 0.48

    upper_leg = _first(positions, "leftUpperLeg", "rightUpperLeg")
    foot = _first(positions, "leftFoot", "rightFoot")
    if upper_leg is not None and foot is not None:
        inseam = float(abs(upper_leg[1] - foot[1]))
        confidence["inseam"] = 0.9
    else:
        inseam = leg * 0.95
        confidence["inseam"] = 0.4

    return BodyMeasurements(
        height_m=height,
        shoulder_width_m=float(shoulder),
        chest_width_m=float(chest),
        waist_width_m=float(waist),
        hip_width_m=float(hip),
        arm_length_m=float(arm),
        leg_length_m=float(leg),
        inseam_m=float(inseam),
        depth_m=float(depth),
        bone_positions={k: tuple(float(c) for c in v) for k, v in positions.items()},
        bounds=(
            (tuple(float(c) for c in bounds[0]), tuple(float(c) for c in bounds[1]))
            if bounds is not None
            else None
        ),
        confidence=confidence,
    )


def _first(positions: dict[str, np.ndarray], *names: str) -> np.ndarray | None:
    """First resolved bone position among ``names`` (``or`` is unsafe on arrays)."""
    for name in names:
        value = positions.get(name)
        if value is not None:
            return value
    return None


def _paired_distance(positions: dict[str, np.ndarray], left: str, right: str) -> float | None:
    a, b = positions.get(left), positions.get(right)
    if a is None or b is None:
        return None
    distance = float(np.linalg.norm(a - b))
    return distance if distance > 1e-5 else None


def _chain_length(positions: dict[str, np.ndarray], bones: list[str]) -> float | None:
    points = [positions.get(bone) for bone in bones]
    if any(p is None for p in points):
        return None
    total = 0.0
    for a, b in zip(points, points[1:], strict=False):
        total += float(np.linalg.norm(b - a))
    return total if total > 1e-5 else None


__all__ = ["BodyMeasurements", "MeasurementError", "measure_body"]
