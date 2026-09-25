"""Where hosiery meets the fitting engine: four hooks, each a no-op for any other garment.

The native engine calls these around its ordinary shell fit. Each one looks at
the garment's ``hosieryRole`` (set by the template provider only for a garment
that is part of a hosiery design) and returns at once when there is none, so a
garment outside a hosiery outfit is fitted by exactly the code it always was.

    before_shell   the outer skirt or dress: solve its hem for the reveal level
    after_shell    stockings: lay the rolled edge and the back seam on the fitted tubes
    after_bind     stockings: publish FittedStockingTop; belt: publish FittedBelt
    fit_connector  the straps and hardware, built from the two contracts
"""

from __future__ import annotations

import numpy as np

from wardrobe.errors import FittingError
from wardrobe.hosiery import stockings as stocking_parts
from wardrobe.hosiery.contract import CLIPS_FOR
from wardrobe.hosiery.garter_belt import publish_belt
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.skinning import build_bone_segments


def role(context) -> str | None:
    artifact = context.artifact
    return artifact.metadata.get("hosieryRole") if artifact is not None else None


def design(context) -> dict:
    return (context.artifact.metadata.get("hosiery") or {}) if context.artifact is not None else {}


def forward(context) -> float:
    """Which way she faces: from her feet where the rig has toes, else from the VRM spec."""
    from wardrobe.geometry.procedural import FitParameters

    fallback = -1.0 if context.info is not None and context.info.spec is VrmSpec.VRM0 else 1.0
    return FitParameters(measurements=context.measurements, metadata={"forward": fallback}).forward


def before_shell(context) -> None:
    """Solve the outer garment's hem for its reveal level, against the published stocking tops."""
    if role(context) not in {"main", "one-piece", "outer"}:
        return
    plan = design(context)
    if not plan.get("reveal") or not context.stocking_tops:
        return
    from wardrobe.hosiery.reveal import solve_hem

    solution = solve_hem(context, plan["reveal"])
    context.reveal = solution
    if solution.get("hemY") is not None:
        context.artifact.metadata["hemY"] = solution["hemY"]


def after_shell(context, mesh):
    """Stockings: the rolled edge and the seam, laid on the tubes where fitting put them."""
    if role(context) != "legwear" or not stocking_parts.tube_layout(mesh):
        return mesh
    plan = design(context).get("stockings") or {}
    mesh = stocking_parts.finish_stockings(mesh, plan, forward=forward(context))
    stocking_parts.stocking_uvs(mesh, plan)
    return mesh


def after_bind(context, mesh, segments) -> None:
    """Publish the contracts: the stocking tops and the belt's lower edge."""
    current = role(context)
    if current == "legwear" and stocking_parts.tube_layout(mesh):
        stocking_parts.copy_seated_weights(mesh)
        belt = design(context).get("belt") or {}
        names = CLIPS_FOR.get(int(belt.get("strapCount") or 4), CLIPS_FOR[4])
        context.stocking_tops = stocking_parts.publish_stocking_tops(
            mesh, segments, context.measurements.bone_positions, forward=forward(context), clip_names=names)
    elif current == "foundation" and mesh.metadata.get("hosieryBeltRing"):
        style = str(context.artifact.metadata.get("beltStyle") or "classic")
        clearance = float(context.artifact.metadata.get("bodyClearanceMm", 2.5)) / 1000.0
        context.belt = publish_belt(mesh, segments, style=style, clearance_m=clearance)


def fit_connector(context):
    """The straps and hardware: mesh, bone segments and a strap-tension record."""
    from wardrobe.engines.geometry_checks import body_points
    from wardrobe.engines.shell import _torso

    # Imported here: the engines package imports this module, and poses imports the engines' checks.
    from wardrobe.hosiery.poses import POSES, mirrored, transforms
    from wardrobe.hosiery.suspender_straps import build_connector, measure_tension

    if context.belt is None or not context.stocking_tops:
        raise FittingError("the suspender straps need a fitted belt and fitted stockings to clip to")
    whole = body_points(context.document)
    torso = _torso(context, whole)
    surroundings = [torso if torso is not None else whole]
    if context.collision_points is not None:
        surroundings.append(context.collision_points)
    belt_plan = design(context).get("belt") or {}
    facing = forward(context)
    pivots = context.measurements.bone_positions
    bones = list(context.info.humanoid_bones)
    # Tabs are chosen against walking both ways (each leg forward) and sitting.
    judge = {"walk": transforms("walk", facing, pivots, bones),
             "walk-other": transforms(mirrored("walk", facing), facing, pivots, bones),
             "sit": transforms("sit", facing, pivots, bones)}
    connector = build_connector(context.belt, context.stocking_tops, np.vstack(surroundings),
                                belt_plan=belt_plan, height=context.measurements.height_m, judge=judge)
    mesh = connector.mesh
    names = sorted({b for bones in connector.bones for b in bones})
    segments = build_bone_segments(context.info.humanoid_bones, context.measurements, names)
    index = {segment.name: i for i, segment in enumerate(segments)}
    if not index:
        raise FittingError("none of the bones the straps attach to exist on this avatar")
    joints = np.zeros((mesh.vertex_count, 4), dtype=np.uint16)
    weights = np.zeros((mesh.vertex_count, 4), dtype=np.float32)
    fallback = next(iter(index.values()))
    for v, (vertex_bones, ws) in enumerate(zip(connector.bones, connector.weights, strict=True)):
        pairs = [(index[b], w) for b, w in zip(vertex_bones, ws, strict=True) if b in index]
        pairs = pairs or [(fallback, 1.0)]
        total = sum(w for _, w in pairs)
        for slot, (j, w) in enumerate(pairs[:4]):
            joints[v, slot] = j
            weights[v, slot] = w / total
    weights[:, 0] += (1.0 - weights.sum(axis=1)).astype(np.float32)
    mesh.joints, mesh.weights = joints, weights
    mesh.metadata["boundBones"] = [s.name for s in segments]
    tables = {pose: transforms(pose, facing, pivots, bones) for pose in POSES}
    # Her body in each pose, round the hips and thighs only: all a strap can touch.
    from wardrobe.hosiery.reveal import posed_bodies

    bodies = posed_bodies(context)
    lift = float(belt_plan.get("strapThicknessM") or 0.0012) / 2.0 + 0.0026  # over the stocking, not skin
    measure_tension(connector.straps, tables=tables, bodies=bodies, lift=lift)
    context.connector = connector
    return mesh, segments


__all__ = ["after_bind", "after_shell", "before_shell", "fit_connector", "forward", "role"]
