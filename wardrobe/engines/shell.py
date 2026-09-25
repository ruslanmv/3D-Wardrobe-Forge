"""Garment shell construction, shared by both engines.

Both engines start from the same measured, clearance-resolved shell. They
diverge afterwards:

* native  — binds the shell to the humanoid rig analytically and writes the VRM.
* blender — shrinkwraps the shell onto the real body surface, transfers weights
  from the body mesh, and deletes the body polygons it covers.

Keeping the shell in one place means garment shape is identical across engines
and only fitting *quality* differs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.domain.looks import ClippingCheck
from wardrobe.engines.geometry_checks import (
    BodyRadialIndex,
    ClearanceReport,
    apply_drape,
    apply_pleats,
    arm_profile,
    armpit_height,
    body_points,
    conform_limbs,
    conform_to_body,
    coverage_report,
    lower_body_profile,
    measure_clearance,
    resolve_clearance,
    select_region_points,
    settle_faces,
    smooth_radial,
    torso_profile,
    upper_body_surface,
)
from wardrobe.errors import FittingError
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.lingerie.landmarks import measure_landmarks
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.skinning import bones_for_coverage, build_bone_segments, connected_components


@dataclass(slots=True)
class ShellResult:
    mesh: Mesh
    index: BodyRadialIndex
    body: np.ndarray
    clearance_m: float
    before: ClearanceReport
    after: ClearanceReport
    verdict: ClippingCheck


def build_fitted_shell(context: PipelineContext) -> ShellResult:
    """Build the garment shell at this avatar's measurements and de-intersect it."""
    if context.info is None or context.measurements is None or context.document is None:
        raise FittingError("avatar analysis must run before fitting")
    if context.plan is None or context.artifact is None:
        raise FittingError("outfit planning must run before fitting")

    artifact = context.artifact
    template = context.catalog.get(artifact.template_id) if artifact.template_id else None
    clearance = float(artifact.metadata.get("bodyClearanceMm", 6.0)) / 1000.0
    if context.collision_points is not None and context.collision_points.shape[0]:
        # Over another garment, allow for its thickness and for this shell's faces
        # dipping between vertices: lace specks showed through an opaque dress
        # at the body clearance alone.
        clearance += INNER_LAYER_ALLOWANCE_M

    metadata = dict(artifact.metadata)
    # Which way she faces, for a rig without toes to say so: VRM 0.x faces -Z.
    metadata.setdefault("forward", -1.0 if context.info.spec is VrmSpec.VRM0 else 1.0)
    whole = body_points(context.document)
    legs = _skinned_to(context, whole, LEG_BONES)
    if legs is not None:
        # Her legs as measured, for anything with legs or a band that stops at the crotch.
        profile = lower_body_profile(whole, legs, context.measurements.bone_positions)
        if profile is not None:
            metadata["lowerBody"] = profile
            # What the leg fit reaches for is leg, below the crotch (see lower_body_profile).
            legs = legs[legs[:, 1] < float(profile["crotchY"]) - 0.01]
    bones = context.info.humanoid_bones
    segments = build_bone_segments(bones, context.measurements, list(bones))
    armpit = armpit_height(whole, segments) if segments else None
    arms = arm_profile(whole, segments) if segments else None
    if arms is not None:
        metadata["armProfile"] = arms
    if armpit is not None:
        metadata["armpitY"] = armpit
    upper = _skinned_to(context, whole, frozenset(bones) - (OUTLINE_EXCLUDED_BONES - {"neck"}))
    if upper is not None:
        surface = upper_body_surface(upper, context.measurements.bone_positions, metadata["forward"],
                                     shoulders=_torso(context, whole))
        if surface is not None:
            metadata["upperBody"] = surface
    kind = artifact.procedural_kind or context.plan.category
    folds = int(artifact.metadata.get("drapeFolds") or 0)
    if folds and kind in SKIRTED_KINDS:
        # Six vertices a fold, or the drape aliases into facets.
        params_segments_floor = folds * 6
    else:
        params_segments_floor = 0
    if kind in SKIRTED_KINDS:
        # Her outline, chest to knee, for the skirt to be cut from (procedural.build_skirt).
        bone_y = {name: float(p[1]) for name, p in context.measurements.bone_positions.items()}
        top = bone_y.get("chest", bone_y.get("spine", 1.0) + 0.1)
        knee = bone_y.get("leftLowerLeg", top - 0.6)
        profile = torso_profile(_torso(context, whole), top, knee)
        if profile is not None:
            metadata["torsoProfile"] = profile
    if kind in LINGERIE_KINDS:
        # A pattern block is placed on her landmarks (wardrobe.lingerie.landmarks):
        # bust points, the fold under the bust, sternum, waist, hips, crotch.
        torso = _torso(context, whole)
        bone_y = {name: float(p[1]) for name, p in context.measurements.bone_positions.items()}
        profile = torso_profile(torso, bone_y.get("neck", 1.4), bone_y.get("leftLowerLeg", 0.4))
        if profile is not None:
            metadata["torsoProfile"] = profile
        marks = measure_landmarks(torso, context.measurements.bone_positions, forward=metadata["forward"],
                                  lower=metadata.get("lowerBody"), armpit_y=metadata.get("armpitY"))
        if marks is not None:
            metadata["lingerieLandmarks"] = marks.to_dict()
            for warning in marks.warnings:
                context.warn(f"lingerie landmarks: {warning}")
    params = FitParameters(
        measurements=context.measurements,
        clearance_m=clearance,
        sleeve_length=context.plan.sleeve,
        metadata=metadata,
    )
    if template is not None and not template.fit.allow_width_scale:
        params.width_scale = 1.0
    if context.plan.material.exposes_body:
        # Through a see-through fabric every clipping error is on show: build it
        # finer, so clearance is checked at more points round the body.
        params.segments = max(params.segments, SHEER_SEGMENTS)
    params.segments = max(params.segments, params_segments_floor)
    pleats = int(artifact.metadata.get("pleats") or 0)
    if pleats:
        # Four vertices a pleat, or the sawtooth aliases into noise.
        params.segments = max(params.segments, pleats * 6)

    # Build the template's own shape. The original five templates share their
    # category's name as their shape; a bikini and a crop top do not.
    mesh = build_garment(kind, params, silhouette=context.plan.silhouette, hem=context.plan.hem)

    region_bones = set(bones_for_coverage(artifact.coverage)) - CLEARANCE_EXCLUDED_BONES
    body = _restrict_to_covered_region(context, whole, region_bones)
    torso = _torso(context, whole)
    inner = context.collision_points
    if inner is not None and inner.shape[0]:
        # The layers already fitted are part of what this one must clear: a
        # dress goes over the underwear, not through it.
        whole = np.vstack([whole, inner])
        body = np.vstack([body, inner])
        torso = inner if torso is None else np.vstack([torso, inner])
        # Stockings under trousers: their legs are what the trouser legs must clear.
        inner_legs = _skinned_to(context, inner, LEG_BONES)
        if inner_legs is not None:
            profile = metadata.get("lowerBody")
            if isinstance(profile, dict):
                inner_legs = inner_legs[inner_legs[:, 1] < float(profile["crotchY"]) - 0.01]
            legs = inner_legs if legs is None else np.vstack([legs, inner_legs])
    heights = (float(mesh.positions[:, 1].min()), float(mesh.positions[:, 1].max()))
    index = BodyRadialIndex(body, surroundings=torso, y_range=heights)

    axis_mask = on_axis_mask(mesh, context.measurements)

    conform = float(artifact.metadata.get("conform") or 0.0)
    leg_conform = conform
    below_hips = bool(artifact.metadata.get("conformBelowHips"))
    if kind in TROUSER_KINDS and conform == 0.0:
        # A trouser yoke sits on her hips like any waistband; its legs keep their
        # cut. Unfitted, the yoke kept a formula's depth and stood 3 cm off her
        # seat and belly on a real avatar.
        conform, below_hips = YOKE_CONFORM, True
    if conform > 0.0:
        conform_to_body(mesh, index, clearance, axis_mask, strength=conform,
                        min_y=None if below_hips else params.hip_y)

    # Leg-worn pieces (stocking and legging tubes, trouser and catsuit legs) are
    # off the body axis; fit them round each leg's own bones instead.
    leg_worn = ~axis_mask & (mesh.positions[:, 1] < params.hip_y + params.height * 0.03)
    if leg_worn.any():
        conform_limbs(mesh, leg_worn, legs if legs is not None and legs.shape[0] else whole,
                      context.measurements.bone_positions, clearance,
                      strength=leg_conform, forward=params.forward)
        _keep_legs_apart(mesh, leg_worn, context.measurements.bone_positions)

    before = measure_clearance(mesh, index, clearance, axis_mask)
    pushed = resolve_clearance(mesh, index, clearance, axis_mask)
    smooth_radial(mesh, index, clearance, axis_mask)
    settle_faces(mesh, index, clearance, axis_mask)
    if pleats:
        # Set from just below the waistband on a skirt, from the hips on a dress.
        pleat_from = params.waist_y - 0.03 if kind == "skirt" else params.hip_y
        apply_pleats(mesh, index, count=pleats, from_y=pleat_from, mask=axis_mask, clearance_m=clearance,
                     amplitude=float(artifact.metadata.get("pleatDepth") or 0.03),
                     retexture=context.plan.material.pattern == "none")
    drape = int(artifact.metadata.get("drapeFolds") or 0)
    if drape and kind in SKIRTED_KINDS:
        apply_drape(mesh, index, folds=drape, amplitude=float(artifact.metadata.get("hemDrape") or 0.0),
                    from_y=params.hip_y, mask=axis_mask, clearance_m=clearance)
    after = measure_clearance(mesh, index, clearance, axis_mask)
    after.resolved = pushed

    # The shell's UVs are metres of fabric; one pattern tile covers its physical size.
    scale = float(context.plan.material.texture_scale or 0.0)
    if scale > 0.0 and mesh.uvs is not None:
        mesh.uvs = (mesh.uvs * scale).astype(np.float32)

    if not after.checked:
        # Nothing on the body's axis to check: the whole garment is limb-worn
        # (a pair of shoes), and was lofted around each limb's own bone with
        # the template's clearance already applied.
        verdict = ClippingCheck.CLEARANCE_ONLY
    elif after.violations == 0:
        verdict = ClippingCheck.PASSED
    elif after.violation_ratio < 0.02:
        verdict = ClippingCheck.WARNINGS
        context.warn(
            f"{after.violations} garment vertices remain within the clearance margin "
            f"({after.violation_ratio:.2%} of the shell)"
        )
    else:
        verdict = ClippingCheck.FAILED
        context.warn(f"garment intersects the body at {after.violation_ratio:.2%} of its vertices")

    return ShellResult(
        mesh=mesh,
        index=index,
        body=body,
        clearance_m=clearance,
        before=before,
        after=after,
        verdict=verdict,
    )


#: Below this many body points the classification is too sparse to trust, and
#: the wider (limb-free) body is used instead. Deliberately small: a low-poly
#: avatar can put only a couple of dozen vertices under a garment.
MIN_REGION_POINTS = 12

#: Never measured against the radial clearance index, even when covered.
#:
#: The index is cylindrical around the body's *vertical* axis, which is simply
#: the wrong frame for a horizontal limb: in a T-pose an outstretched arm fills
#: every height band at shoulder level out to the fingertips. Sleeves do not
#: need it — they are swept along the arm bone chain at a radius already
#: derived from that arm, plus the template's clearance.
CLEARANCE_EXCLUDED_BONES = frozenset(
    {
        "leftShoulder", "rightShoulder",
        "leftUpperArm", "rightUpperArm",
        "leftLowerArm", "rightLowerArm",
        "leftHand", "rightHand",
        "neck", "head",
    }
)


#: A garment component whose centre sits further from the midline than this
#: fraction of the leg separation is worn on one limb, not on the body.
LIMB_OFFSET_FRACTION = 0.35
#: ... or further off it than this fraction of its own half-width.
LIMB_OFFSET_OF_WIDTH = 0.35


def on_axis_mask(mesh: Mesh, measurements) -> np.ndarray:
    """Vertices the body-axis clearance index can actually speak for.

    ``BodyRadialIndex`` is cylindrical around the body's single vertical axis.
    That is the right frame for a bodice or a skirt, and the wrong one for
    anything worn on a *pair* of limbs: the axis falls between the two feet,
    not inside either, so a trouser leg's inner surface reads as buried in the
    body and gets pushed outward.

    Connected components decide it, the same signal used for skin binding: a
    component centred off the midline is limb-worn and is left as built —
    those pieces are lofted around their own bone with the clearance already
    applied.
    """
    full = np.ones(mesh.vertex_count, dtype=bool)

    left = measurements.bone_positions.get("leftUpperLeg")
    right = measurements.bone_positions.get("rightUpperLeg")
    if left is None or right is None:
        return full

    centre = (float(left[0]) + float(right[0])) * 0.5
    separation = abs(float(left[0]) - float(right[0]))
    if separation < 1e-4:
        return full

    tolerance = separation * LIMB_OFFSET_FRACTION
    labels = connected_components(mesh)
    x = mesh.positions[:, 0].astype(np.float64)

    for label in np.unique(labels):
        member = labels == label
        offset = abs(float(x[member].mean()) - centre)
        half_width = float(x[member].max() - x[member].min()) * 0.5
        # Off the midline by a good part of its own width is a limb piece too. The
        # spacing test alone called a pair of baggy legs torso on a knock-kneed
        # avatar — 5.5 cm off a 4.8 cm tolerance, one wider cut from failing — and
        # the torso fit pushed both legs out to one 36 cm bulge.
        if offset > tolerance or offset > half_width * LIMB_OFFSET_OF_WIDTH:
            full[member] = False
    return full


def _restrict_to_covered_region(
    context: PipelineContext, body: np.ndarray, region_bones: set[str]
) -> np.ndarray:
    """Measure clearance against the body parts the garment actually sits on.

    A sleeveless dress must not be pushed outward to clear the arms just
    because they share a height band with the chest.
    """
    if body.shape[0] == 0 or context.info is None or context.measurements is None:
        return body
    if not region_bones:
        return body

    all_bones = list(context.info.humanoid_bones)
    segments = build_bone_segments(context.info.humanoid_bones, context.measurements, all_bones)
    if not segments:
        return body

    selected = body[select_region_points(body, segments, region_bones)]
    if selected.shape[0] >= MIN_REGION_POINTS:
        return selected

    # Too sparse to trust. Widen to everything except the limbs the radial
    # index cannot represent — never back to the whole body, which would
    # reintroduce exactly the arms this function exists to remove.
    wider = {bone for bone in context.info.humanoid_bones if bone not in CLEARANCE_EXCLUDED_BONES}
    fallback = body[select_region_points(body, segments, wider)]
    context.warn(
        "too few body vertices under this garment to isolate its region; "
        "clearance was measured against the whole torso and legs"
    )
    return fallback if fallback.shape[0] >= MIN_REGION_POINTS else body


#: Radial resolution of a see-through garment's shell (the default is 32).
SHEER_SEGMENTS = 48

#: Extra clearance for a garment going on over another one (see build_fitted_shell).
INNER_LAYER_ALLOWANCE_M = 0.003

#: Never part of the body's outline for a torso garment: they share height bands
#: with it (a T-pose arm, the head above a collar) without being under it.
OUTLINE_EXCLUDED_BONES = frozenset(
    {
        "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm",
        "leftHand", "rightHand", "neck", "head",
    }
)


#: Garment shapes with a skirt: cut from her measured outline (see ``torso_profile``).
SKIRTED_KINDS = frozenset({"skirt", "dress", "slip-dress", "swim-dress"})

#: Garment shapes with a yoke over the hips and a leg per leg.
TROUSER_KINDS = frozenset({"trousers", "pants", "jeans", "shorts"})

#: How closely a trouser yoke is drawn onto her hips when the template says nothing.
YOKE_CONFORM = 0.9

#: The gap kept between two trouser legs at her midline, in metres.
LEG_GAP_M = 0.003


def _keep_legs_apart(mesh: Mesh, leg_worn: np.ndarray, bones: dict) -> None:
    """Each leg-worn piece stays on its own side of her midline.

    On a figure whose thighs touch, a leg's inner side — pushed out of her
    inner thigh, or cut wider than it — crossed into the other leg. The two
    interpenetrated and a pair of jeans read as one column. Held a few
    millimetres short of the midline, the legs meet in a seam and read as two.
    """
    left, right = bones.get("leftUpperLeg"), bones.get("rightUpperLeg")
    if left is None or right is None or not leg_worn.any():
        return
    centre = (float(left[0]) + float(right[0])) * 0.5
    labels = connected_components(mesh)
    x = mesh.positions[:, 0]
    moved = False
    for label in np.unique(labels[leg_worn]):
        member = (labels == label) & leg_worn
        side = np.sign(float(x[member].mean()) - centre)
        if side == 0:
            continue
        crossing = member & ((x - centre) * side < LEG_GAP_M)
        if crossing.any():
            x[crossing] = centre + side * LEG_GAP_M
            moved = True
    if moved:
        mesh.positions[:, 0] = x
        mesh.compute_normals()


#: What a leg is, for fitting leg-worn pieces: the pelvis beside the hip joint is not.
LEG_BONES = frozenset({"leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg"})


def _skinned_to(context: PipelineContext, body: np.ndarray, bones: frozenset[str]) -> np.ndarray | None:
    if body.shape[0] == 0 or context.info is None or context.measurements is None:
        return None
    all_bones = list(context.info.humanoid_bones)
    segments = build_bone_segments(context.info.humanoid_bones, context.measurements, all_bones)
    if not segments:
        return None
    selected = body[select_region_points(body, segments, set(bones))]
    return selected if selected.shape[0] >= MIN_REGION_POINTS else None


def _torso(context: PipelineContext, body: np.ndarray) -> np.ndarray | None:
    """The whole torso and legs, shoulders included: what the hull outline is taken from.

    Wider than the covered region on purpose — see ``BodyRadialIndex``'s
    ``surroundings``: the sides of her chest may be weighted to the shoulders.
    """
    if body.shape[0] == 0 or context.info is None or context.measurements is None:
        return None
    all_bones = list(context.info.humanoid_bones)
    segments = build_bone_segments(context.info.humanoid_bones, context.measurements, all_bones)
    if not segments:
        return None
    keep = {bone for bone in context.info.humanoid_bones if bone not in OUTLINE_EXCLUDED_BONES}
    return body[select_region_points(body, segments, keep)]


def shell_coverage(result: ShellResult, artifact_coverage: list[str]) -> dict:
    """The coverage/clearance block written into the fit report."""
    return {
        "regions": list(artifact_coverage),
        "clearanceBefore": result.before.to_dict(),
        "clearanceAfter": result.after.to_dict(),
        **coverage_report(result.index, result.mesh, result.body),
    }


__all__ = ["ShellResult", "build_fitted_shell", "shell_coverage"]
