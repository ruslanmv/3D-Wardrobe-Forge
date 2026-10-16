"""Stage 8 — write the derived VRM."""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.engines.base import FittingEngine
from wardrobe.errors import OutputInvalid
from wardrobe.pipeline.context import PipelineContext


async def run(context: PipelineContext, engine: FittingEngine) -> None:
    await context.emit(JobState.EXPORTING, "exporting the derived VRM")

    surface = context.body_surface
    if surface is not None and surface.detail_level == "render" and surface.morphs:
        # BS3. Made regions go into her body mesh as morph targets, appended after any it has.
        # The Blender engine writes the VRM from its own copy of the source, so they would be
        # lost there: said so in the report, never claimed.
        if engine.name == "native":
            from wardrobe.body_surface.export import export_morphs

            names = export_morphs(context.document, surface)
            context.fit_report.body_surface["exportedMorphTargets"] = names
        else:
            context.fit_report.body_surface["exportedMorphTargets"] = []
            context.warn(f"body surface: morph targets are not exported by the {engine.name} engine")

    await engine.assemble(context)

    if not context.output_bytes:
        raise OutputInvalid("the engine produced an empty VRM")
    if len(context.output_bytes) > context.settings.max_output_bytes:
        raise OutputInvalid(
            f"generated VRM is {len(context.output_bytes)} bytes, over the "
            f"{context.settings.max_output_bytes} byte limit"
        )

    await context.emit(
        JobState.EXPORTING,
        f"exported {len(context.output_bytes)} bytes",
        sizeBytes=len(context.output_bytes),
    )


__all__ = ["run"]
