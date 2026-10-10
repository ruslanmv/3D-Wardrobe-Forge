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
    apply_knife_pleats,
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
    taut_columns,
    torso_profile,
    upper_body_surface,
)
from wardrobe.errors import FittingError
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import (
    PLEAT_SET_M,
    TROUSER_WAISTBAND_M,
    FitParameters,
    build_garment,
    flare_start_y,
    front_angle,
    full_hip_y,
    skirt_shape,
    skirt_top,
    trouser_top,
    trouser_top_dip,
)
from wardrobe.geometry.waistband import FITTED_WAISTBAND_PROUD_M, add_hem_facing, add_waistband
from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.skinning import bones_for_coverage, build_bone_segments, connected_components

#: S6. Over how much height a fitted skirt rounds the bends of her hip (taut_columns).
TAUT_ROUND_M = 0.02
#: S6. Over how much height a fitted skirt's conforming eases out above her full hip.
CONFORM_FADE_M = 0.03

#: S4/S5. Columns a pleat on a skirt with its own waistband row: seven or eight across the
#: visible face, two on the hidden underfold and two on its return (apply_knife_pleats).
PLEAT_COLUMNS = 12


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
    if kind == "boots":
        # DC2. Her feet and legs as she stands (wardrobe.vrm.stance), each side its own, and any
        # layer already fitted on them this job: the boot is cut round all of it.
        from wardrobe.vrm.visible import drawn_surface

        hip = context.measurements.bone_positions.get("hips")
        drawn = drawn_surface(context.document, y_max=float(hip[1]) if hip is not None else 1.0)
        reach = drawn if context.collision_points is None else np.vstack([drawn, context.collision_points])
        metadata["bootBody"] = _boot_body(context, reach)
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
        from wardrobe.lingerie.landmarks import measure_landmarks  # it imports this package

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
    band_m = float(artifact.metadata.get("waistbandMm") or 0.0) / 1000.0
    if pleats:
        # Four vertices a pleat, or the sawtooth aliases into noise.
        params.segments = max(params.segments, pleats * 6)
        if band_m and kind == "skirt":
            # S4. A whole number of columns a pleat, at least eight: with the columns an even
            # length of fabric apart (build_skirt's ``even``) every fold falls on a column,
            # the same column on every row, so a pressed edge runs straight down the skirt
            # instead of stepping between facets.
            params.segments = pleats * max(-(-params.segments // pleats), PLEAT_COLUMNS)

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
    # A pattern block marks what it places itself (a brief's gusset crosses under her,
    # where pushing out from her vertical axis means nothing): the radial passes leave it.
    placed = mesh.metadata.get("placed")
    if placed is not None:
        axis_mask = axis_mask & ~placed

    conform = float(artifact.metadata.get("conform") or 0.0)
    leg_conform = conform
    below_hips = bool(artifact.metadata.get("conformBelowHips"))
    if kind in TROUSER_KINDS and conform == 0.0:
        # A trouser yoke sits on her hips like any waistband; its legs keep their
        # cut. Unfitted, the yoke kept a formula's depth and stood 3 cm off her
        # seat and belly on a real avatar.
        conform, below_hips = YOKE_CONFORM, True
    conform_floor, conform_fade = params.hip_y, 0.0
    if kind == "skirt" and artifact.metadata.get("conformTo") == "full-hip":
        # S6. A fitted skirt is drawn onto her down to her full hip, not only to the hip
        # joint: on AvatarSample A the joint is above the widest part of her seat, and the
        # skirt stood 10 mm off it there while it was 6 mm off at the waist. Below the full
        # hip it hangs straight, never back in toward her thighs (build_skirt).
        conform_floor, conform_fade = min(params.hip_y, full_hip_y(params)), CONFORM_FADE_M
    if conform > 0.0:
        conform_to_body(mesh, index, clearance, axis_mask, strength=conform,
                        min_y=None if below_hips else conform_floor, fade_m=conform_fade)

    # Leg-worn pieces (stocking and legging tubes, trouser and catsuit legs) are
    # off the body axis; fit them round each leg's own bones instead.
    leg_worn = ~axis_mask & (mesh.positions[:, 1] < params.hip_y + params.height * 0.03)
    if placed is not None:
        leg_worn &= ~placed
    if leg_worn.any():
        conform_limbs(mesh, leg_worn, legs if legs is not None and legs.shape[0] else whole,
                      context.measurements.bone_positions, clearance,
                      strength=leg_conform, forward=params.forward)
        _keep_legs_apart(mesh, leg_worn, context.measurements.bone_positions)

    before = measure_clearance(mesh, index, clearance, axis_mask)
    pushed = resolve_clearance(mesh, index, clearance, axis_mask)
    smooth_radial(mesh, index, clearance, axis_mask)
    settle_faces(mesh, index, clearance, axis_mask)
    if band_m and kind == "skirt" and artifact.metadata.get("conformTo") == "full-hip":
        # S6. Taut over the hip: no facet of her body printed through a skirt fitted this close.
        shape = skirt_shape(params, context.plan.silhouette, 1.0)
        top, hem_y = float(mesh.positions[:, 1].max()), float(mesh.positions[:, 1].min())
        taut_columns(mesh, index, top=top, mask=axis_mask, round_m=TAUT_ROUND_M,
                     bottom=flare_start_y(params, shape, y_top=top, y_bottom=hem_y))
    if kind in LINGERIE_KINDS:
        from wardrobe.lingerie.fit import after_shell as seat_placed  # it imports this package

        seat_placed(context, mesh, clearance)
    if pleats:
        # Set from just below the waistband on a skirt, from the hips on a dress.
        # From just below the skirt's own top: a low-rise skirt starts below her waist (P1).
        pleat_from = skirt_top(params) - 0.03 if kind == "skirt" else params.hip_y
        if band_m and kind == "skirt":
            # S4. From the stitching line under the band (build_skirt puts a row there), so
            # the band is plain and every pleat starts on the same line.
            pleat_from = skirt_top(params) - band_m - PLEAT_SET_M + 1e-4
        depth_of_pleat = float(artifact.metadata.get("pleatDepth") or 0.03)
        if band_m and kind == "skirt":
            # S5. Knife pleats with a face, a fold edge and an underfold, not a sawtooth.
            # The creases add vertices; the axis mask follows them.
            hem_now = float(mesh.positions[:, 1].min())
            hip_line = min(max(full_hip_y(params), hem_now + 0.02), pleat_from)
            mid = (hip_line + hem_now) / 2.0
            # S6. Closed at the hip, open at the hem: how far each pleat's fold has opened
            # at her upper hip, full hip, mid skirt and hem.
            opening = [(pleat_from, 0.0), ((pleat_from + hip_line) / 2.0, 0.15), (hip_line, 0.30),
                       (mid, 0.68), (hem_now, 1.0)]
            origin = apply_knife_pleats(mesh, index, count=pleats, from_y=pleat_from, mask=axis_mask,
                                        clearance_m=clearance, step=depth_of_pleat, opening=opening,
                                        retexture=context.plan.material.pattern == "none")
            if origin is not None:
                axis_mask = axis_mask[origin]
        else:
            apply_pleats(mesh, index, count=pleats, from_y=pleat_from, mask=axis_mask, clearance_m=clearance,
                         amplitude=depth_of_pleat, retexture=context.plan.material.pattern == "none")
    drape = int(artifact.metadata.get("drapeFolds") or 0)
    if drape and kind in SKIRTED_KINDS:
        apply_drape(mesh, index, folds=drape, amplitude=float(artifact.metadata.get("hemDrape") or 0.0),
                    from_y=params.hip_y, mask=axis_mask, clearance_m=clearance)
    after = measure_clearance(mesh, index, clearance, axis_mask)
    after.resolved = pushed
    if kind == "skirt":
        # Last, from the finished shape: a band built before fitting is pressed back
        # into the skirt by the passes above (wardrobe.geometry.waistband).
        if band_m:
            # S4. A turned hem on a skirt cut with its own band: a fold with a thickness, before
            # the band, whose rows it never reaches.
            mesh = add_hem_facing(mesh, index.axis_x, index.axis_z)
        # S5. A cut band sits 1.8 mm proud, not 3: over the skirt's own ease, 3 mm read as a
        # belt floating round her. The darker shade and the ledge mark it, not the gap.
        cut_band = {"depth_m": band_m + 1e-4, "proud_m": FITTED_WAISTBAND_PROUD_M} if band_m else {}
        mesh = add_waistband(mesh, index.axis_x, index.axis_z, **cut_band)
    elif kind == "trousers" and str(params.metadata.get("rise") or "") in {"low", "ultra-low"}:
        # P2. Low-rise jeans get a narrow waistband that follows their curved top edge. The
        # yoke alone read as a thick blue belt: nothing marked where the band ended and the
        # jeans began. Other rises keep the trousers they always had.
        rise = str(params.metadata["rise"])
        top = trouser_top(params, rise)
        mesh = add_waistband(
            mesh, index.axis_x, index.axis_z, depth_m=TROUSER_WAISTBAND_M + 0.002, section="trousers-yoke",
            top_edge=lambda points: top + trouser_top_dip(front_angle(points, params), rise, params.height),
        )
    elif kind in LINGERIE_KINDS and artifact.metadata.get("collection"):
        # LC2. A collection piece's lace, binding, bows and metal, sewn onto the fabric as it
        # was fitted — after the clearance is measured, whose masks are the panels' own.
        from wardrobe.lingerie.atelier import embellish

        mesh = embellish(mesh, artifact.metadata["collection"], params)

    _light_gusset(mesh, params.forward)
    if kind in SEAM_WELDED_KINDS:
        _weld_seam_normals(mesh)

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


#: DC3. Garments built of a bodice and a skirt whose shading must run straight across the join.
SEAM_WELDED_KINDS = frozenset({"dress", "slip-dress"})
#: How close two open edges of different pieces must be to count as one seam.
SEAM_WELD_M = 0.004


def _weld_seam_normals(mesh: Mesh) -> None:
    """DC3. One normal either side of the join between a dress's bodice and its skirt.

    The two are separate pieces a millimetre apart, and each piece's normals at its own edge
    lean the way only its own faces do. Matte, nobody saw it; in satin or patent the
    highlight broke along a hard line round her hips. Paired open-edge vertices of different
    pieces that already face the same way share their mean normal; the shape is untouched.
    A strap's open end beside the neckline faces another way and is left alone.
    """
    if mesh.normals is None or mesh.indices.size == 0:
        return
    tris = mesh.indices.reshape(-1, 3).astype(np.int64)
    edges = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    open_vertices = np.unique(unique[counts == 1])
    if open_vertices.size < 2:
        return
    labels = connected_components(mesh)
    points = mesh.positions[open_vertices].astype(np.float64)
    normals = mesh.normals[open_vertices].astype(np.float64)
    owner = labels[open_vertices]
    gap = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    facing = normals @ normals.T
    paired = (gap < SEAM_WELD_M) & (owner[:, None] != owner[None, :]) & (facing > 0.5)
    if not paired.any():
        return
    weights = paired.astype(np.float64) + np.eye(open_vertices.size)
    merged = weights @ normals
    merged /= np.maximum(np.linalg.norm(merged, axis=1, keepdims=True), 1e-12)
    rows = paired.any(axis=1)
    mesh.normals = mesh.normals.copy()
    mesh.normals[open_vertices[rows]] = merged[rows].astype(np.float32)


#: T1. How far down a crotch gusset's shading normals tip from horizontal (about 20 degrees).
GUSSET_NORMAL_DOWN = 0.35


def _light_gusset(mesh: Mesh, forward: float) -> None:
    """T1. Shade a crotch gusset as the cloth curving under her that it stands for.

    The gusset is flat and faces straight down, so a toon material lit from above gives it
    nothing but its shade colour: a black patch between the legs of beige trousers. Its
    normals are set as a crotch seam's would be — the front half facing forward, the back
    half back, both tipped down — so it takes the light the fabric round it takes. Last,
    after every pass that recomputes normals; the shape is left exactly as it is.
    """
    mask = mesh.metadata.get("gusset")
    if mask is None or mesh.normals is None:
        return
    mask = np.asarray(mask, dtype=bool)
    if mask.shape[0] < mesh.vertex_count:  # a pass appended vertices (add_waistband): none are gusset
        mask = np.concatenate([mask, np.zeros(mesh.vertex_count - mask.shape[0], dtype=bool)])
    mask = mask[: mesh.vertex_count]
    if not mask.any():
        return
    z = mesh.positions[mask, 2].astype(np.float64)
    centre = (z.max() + z.min()) * 0.5
    side = np.where((z - centre) * forward >= 0.0, forward, -forward)
    normals = np.column_stack([np.zeros_like(z), np.full_like(z, -GUSSET_NORMAL_DOWN), side])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    mesh.normals[mask] = normals.astype(np.float32)


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


def _boot_body(context: PipelineContext, body: np.ndarray) -> dict:
    """Her points on each leg and foot, for a boot (wardrobe.geometry.boots)."""
    out = {}
    for side in ("left", "right"):
        bones = frozenset({f"{side}Foot", f"{side}LowerLeg", f"{side}UpperLeg"})
        points = _skinned_to(context, body, bones)
        if points is not None:
            out[side] = points
    return out


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
