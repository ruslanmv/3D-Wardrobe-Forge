"""Stages 5-7 — fit each garment, bind weights and resolve clipping.

The engine does the work; this stage reports it. Fitting, skinning and clipping
are one geometric operation, so they share an engine call and are surfaced as
three states purely so the client can show meaningful progress.

A layered outfit is fitted inner first. Each fitted layer's surface joins what
the next one must clear, so a dress sits over the underwear under it instead of
through it, and nothing is re-measured: the body's measurements were taken once,
on the prepared body, and a bra does not change her chest size. The engine
fits one garment at a time; this stage points the context at each layer in turn.
"""

from __future__ import annotations

import numpy as np

from wardrobe.domain.jobs import JobState
from wardrobe.domain.looks import ClippingCheck
from wardrobe.engines.base import FittingEngine
from wardrobe.engines.geometry_checks import SURFACE_SPACING_M, _surface_samples
from wardrobe.hosiery import report as hosiery_report
from wardrobe.pipeline.context import BuiltLayer, PipelineContext

#: Worst first: the outfit's verdict is its worst layer's.
_SEVERITY = [ClippingCheck.FAILED, ClippingCheck.WARNINGS, ClippingCheck.CLEARANCE_ONLY, ClippingCheck.PASSED]


async def run(context: PipelineContext, engine: FittingEngine) -> None:
    outfit = context.plan
    garments = outfit.garments
    artifacts = context.artifacts or [context.artifact]
    await context.emit(
        JobState.FITTING,
        f"fitting {len(garments)} garment(s) with the {engine.name} engine",
        layers=len(garments),
    )

    context.built = []
    context.collision_points = None
    entries = []
    for garment, artifact in zip(garments, artifacts, strict=True):
        context.plan, context.artifact = garment, artifact
        await engine.fit_garment(context)
        relaxation = _relax(context)
        entry = _entry(context, garment)
        if relaxation is not None:
            entry["relaxation"] = relaxation
        entries.append(entry)
        if context.mesh is not None:
            context.built.append(BuiltLayer(garment, artifact, context.mesh, list(context.segments), entry))
            context.collision_points = _with_surface(context.collision_points, context.mesh)
    context.plan = outfit
    context.engine_name = engine.name
    if context.body_surface is not None and context.fit_report.body_surface is not None:
        context.fit_report.body_surface["clearance"] = _clearance(context)

    report = context.fit_report
    report.layers = entries
    if len(entries) > 1:
        report.garment_vertices = sum(e["vertices"] for e in entries)
        report.garment_triangles = sum(e["triangles"] for e in entries)
        report.weights_valid = all(e["weightsValid"] for e in entries)
        report.bones_used = sorted({bone for e in entries for bone in e["bonesUsed"]})
        worst = min((ClippingCheck(e["clippingCheck"]) for e in entries), key=_rank)
        report.clipping_check = worst

    if outfit is not None and outfit.hosiery is not None:
        report.hosiery = hosiery_report.build(context)
        for message in (report.hosiery or {}).get("warnings", []):
            context.warn(f"hosiery: {message}")
        for message in (report.hosiery or {}).get("errors", []):
            context.warn(f"hosiery: {message}")

    from wardrobe.lingerie import report as lingerie_report  # imports the engines

    report.lingerie = lingerie_report.build(context)
    for message in (report.lingerie or {}).get("warnings", []):
        context.warn(f"lingerie: {message}")

    await context.emit(
        JobState.SKINNING,
        f"bound {report.garment_vertices} vertices to {len(report.bones_used)} bones",
        vertices=report.garment_vertices,
        triangles=report.garment_triangles,
        bones=len(report.bones_used),
    )

    clearance = (context.fit_report.coverage or {}).get("clearanceAfter", {})
    await context.emit(
        JobState.CLIPPING,
        f"clipping check: {report.clipping_check}",
        clippingCheck=str(report.clipping_check),
        verticesPushedOut=clearance.get("verticesPushedOut", 0),
    )


#: BS5. Garments the relaxation leaves as fitted: rigid boots, and anything not built as a shell.
RIGID_KINDS = frozenset({"boots"})


def _relax(context: PipelineContext) -> dict | None:
    """BS5. XPBD-relax the layer just fitted against the collision body, when the job asked for it."""
    surface = context.body_surface
    options = context.record.request.options
    mesh = context.mesh
    if surface is None or options.cloth_relaxation != "xpbd" or mesh is None:
        return None
    artifact = context.artifact
    kind = (artifact.procedural_kind if artifact is not None else None) or context.plan.category
    if kind in RIGID_KINDS or (context.artifact is not None
                               and context.artifact.metadata.get("hosieryRole") == "connector"):
        return {"solver": "xpbd", "skipped": f"{kind} is not relaxed"}
    from wardrobe.body_surface.collision import signed_clearance
    from wardrobe.body_surface.xpbd import relax

    positions, report = relax(mesh.positions, mesh.indices, surface.collision_grid())
    out = report.to_dict()
    if not report.moved_vertices:
        return out
    # Kept only if it made her render body's clearance no worse. In a narrow hollow (the gap
    # between her thighs below the crotch) the nearest surface can be either wall, and a contact
    # push there can go the wrong way: a relaxation that cannot show it helped is not applied.
    render = surface.render_grid()
    before = signed_clearance(render, mesh.positions.astype("float64"), mesh.indices)
    after = signed_clearance(render, positions, mesh.indices)
    worse = (after.get("minimumSignedDistanceMm", 0.0) < before.get("minimumSignedDistanceMm", 0.0) - 1e-3
             or after.get("samplesBelowMinus0_5Mm", 0) > before.get("samplesBelowMinus0_5Mm", 0))
    out["renderClearanceBefore"] = before.get("minimumSignedDistanceMm")
    out["renderClearanceAfter"] = after.get("minimumSignedDistanceMm")
    if worse:
        out["applied"] = False
        out["reason"] = "would have made her clearance worse; the fitted garment is kept as fitted"
        context.warn(f"cloth relaxation not applied to {context.plan.name}: it would not have improved "
                     "clearance")
        return out
    mesh.positions = positions.astype(mesh.positions.dtype)
    mesh.compute_normals()
    out["applied"] = True
    return out


def _clearance(context: PipelineContext) -> list[dict]:
    """BS2. Each layer's signed clearance from her render body (what would show)."""
    from wardrobe.body_surface.collision import signed_clearance

    grid = context.body_surface.render_grid()
    return [{"layer": layer.plan.name, **signed_clearance(grid, layer.mesh.positions.astype("float64"),
                                                          layer.mesh.indices)}
            for layer in context.built]


def _rank(check: ClippingCheck) -> int:
    return _SEVERITY.index(check) if check in _SEVERITY else 0


def _entry(context: PipelineContext, garment) -> dict:
    report = context.fit_report
    return {
        "id": f"layer-{garment.layer}-{garment.template_id or garment.category}",
        "name": garment.name,
        "role": garment.role,
        "layer": garment.layer,
        "templateId": garment.template_id,
        "clippingCheck": str(report.clipping_check),
        "vertices": report.garment_vertices,
        "triangles": report.garment_triangles,
        "weightsValid": report.weights_valid,
        "bonesUsed": list(report.bones_used),
        "clearance": (report.coverage or {}).get("clearanceAfter", {}),
        "design": garment.design_sheet(
            context.catalog.get(garment.template_id) if garment.template_id else None,
            removed=context.fit_report.base_body.get("removedMaterials", []),
            inner=[layer.plan.name for layer in context.built],
        ),
    }


def _with_surface(points: np.ndarray | None, mesh) -> np.ndarray:
    """A fitted layer's vertices and surface samples: the collision envelope for the next."""
    positions = mesh.positions.astype(np.float64)
    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    surface = np.vstack([positions, _surface_samples(positions, triangles, SURFACE_SPACING_M)])
    return surface if points is None else np.vstack([points, surface])


__all__ = ["run"]
