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
    body_points,
    coverage_report,
    measure_clearance,
    resolve_clearance,
    select_region_points,
)
from wardrobe.errors import FittingError
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.pipeline.context import PipelineContext
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

    params = FitParameters(
        measurements=context.measurements,
        clearance_m=clearance,
        sleeve_length=context.plan.sleeve,
        metadata=dict(artifact.metadata),
    )
    if template is not None and not template.fit.allow_width_scale:
        params.width_scale = 1.0

    mesh = build_garment(
        context.plan.category, params, silhouette=context.plan.silhouette, hem=context.plan.hem
    )

    region_bones = set(bones_for_coverage(artifact.coverage)) - CLEARANCE_EXCLUDED_BONES
    body = body_points(context.document)
    body = _restrict_to_covered_region(context, body, region_bones)
    index = BodyRadialIndex(body)

    axis_mask = on_axis_mask(mesh, context.measurements)

    before = measure_clearance(mesh, index, clearance, axis_mask)
    pushed = resolve_clearance(mesh, index, clearance, axis_mask)
    after = measure_clearance(mesh, index, clearance, axis_mask)
    after.resolved = pushed

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
        if abs(float(x[member].mean()) - centre) > tolerance:
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


def shell_coverage(result: ShellResult, artifact_coverage: list[str]) -> dict:
    """The coverage/clearance block written into the fit report."""
    return {
        "regions": list(artifact_coverage),
        "clearanceBefore": result.before.to_dict(),
        "clearanceAfter": result.after.to_dict(),
        **coverage_report(result.index, result.mesh, result.body),
    }


__all__ = ["ShellResult", "build_fitted_shell", "shell_coverage"]
