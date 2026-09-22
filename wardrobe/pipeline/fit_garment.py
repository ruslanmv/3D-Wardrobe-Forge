"""Stages 5-7 — fit the garment, bind weights and resolve clipping.

The engine does the work; this stage reports it. Fitting, skinning and clipping
are one geometric operation, so they share an engine call and are surfaced as
three states purely so the client can show meaningful progress.
"""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.engines.base import FittingEngine
from wardrobe.pipeline.context import PipelineContext


async def run(context: PipelineContext, engine: FittingEngine) -> None:
    await context.emit(JobState.FITTING, f"fitting the garment with the {engine.name} engine")

    await engine.fit_garment(context)
    context.engine_name = engine.name

    report = context.fit_report
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


__all__ = ["run"]
