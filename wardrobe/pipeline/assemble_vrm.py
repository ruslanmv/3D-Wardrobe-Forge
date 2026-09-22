"""Stage 8 — write the derived VRM."""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.engines.base import FittingEngine
from wardrobe.errors import OutputInvalid
from wardrobe.pipeline.context import PipelineContext


async def run(context: PipelineContext, engine: FittingEngine) -> None:
    await context.emit(JobState.EXPORTING, "exporting the derived VRM")

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
