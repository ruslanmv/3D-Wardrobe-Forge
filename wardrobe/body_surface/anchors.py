"""BS3. Where on her a region sits: anchors from the landmarks Forge already measures.

Every anchor is derived from :func:`wardrobe.lingerie.landmarks.measure_landmarks` — the same
waist, hips, crotch, sternum, bust points and centre-front line a bra or a brief is placed by —
and from nothing else. In particular, nothing about a region is inferred from a character's
name, a prompt, her clothes or a guessed gender: a region goes where the *profile* says, on
landmarks of her measured surface, or it is not placed.

The navel is not measured directly (a VRoid torso has no vertex that is "the navel"); it is
put on her centre-front line between her natural waist and high hip, where the surface
anatomy references put it, and the template's own landmarks then register to that.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.engines.geometry_checks import armpit_height, body_points, lower_body_profile
from wardrobe.lingerie.landmarks import BodyLandmarks, measure_landmarks
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.skinning import build_bone_segments

#: The navel, as a fraction of the way from her natural waist down to her high hip.
NAVEL_FROM_WAIST = 0.3
#: The centre-front anchor above the crotch line, metres.
CROTCH_FRONT_LIFT_M = 0.03


@dataclass(frozen=True)
class Anchor:
    name: str
    position: np.ndarray
    forward: np.ndarray  # the direction the region's surface faces


def measured_landmarks(context) -> BodyLandmarks | None:
    """Her landmarks, measured the way the shell fitter measures them for a lingerie block."""
    from wardrobe.engines.shell import LEG_BONES, _skinned_to, _torso  # the shell imports the pipeline

    whole = body_points(context.document)
    bones = context.measurements.bone_positions
    legs = _skinned_to(context, whole, LEG_BONES)
    lower = lower_body_profile(whole, legs, bones) if legs is not None else None
    humanoid = context.info.humanoid_bones
    segments = build_bone_segments(humanoid, context.measurements, list(humanoid))
    armpit = armpit_height(whole, segments) if segments else None
    # Which way she faces, as the shell fitter decides it: VRM 0.x faces -Z.
    forward = -1.0 if context.info.spec is VrmSpec.VRM0 else 1.0
    return measure_landmarks(_torso(context, whole), bones, forward=forward, lower=lower, armpit_y=armpit)


def locate(name: str, marks: BodyLandmarks) -> Anchor | None:
    """The named anchor on her, or None when her landmarks cannot place it."""
    forward = np.array([0.0, 0.0, marks.forward])
    cx = marks.centre_x

    def front(y: float) -> np.ndarray:
        return np.array([cx, y, marks.front_z(y)])

    if name == "navel":
        y = marks.waist_y - NAVEL_FROM_WAIST * (marks.waist_y - marks.high_hip_y)
        return Anchor(name, front(y), forward)
    if name == "sternum" and marks.sternum:
        return Anchor(name, np.asarray(marks.sternum, dtype=np.float64), forward)
    if name in ("bust-left", "bust-right"):
        point = marks.bust_points.get(name.split("-")[1])
        if point is None or marks.sources.get("bust") == "formula":
            return None
        return Anchor(name, np.asarray(point, dtype=np.float64), forward)
    if name == "centre-front-crotch":
        return Anchor(name, front(marks.crotch_y + CROTCH_FRONT_LIFT_M), forward)
    return None


def landmark_points(marks: BodyLandmarks) -> dict[str, np.ndarray]:
    """Every anchor her landmarks can place, for a template's bound landmarks to register to."""
    out = {}
    for name in ("navel", "sternum", "bust-left", "bust-right", "centre-front-crotch"):
        anchor = locate(name, marks)
        if anchor is not None:
            out[name] = anchor.position
    return out


__all__ = ["Anchor", "landmark_points", "locate", "measured_landmarks"]
