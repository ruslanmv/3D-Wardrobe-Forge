"""Stages 3 and 4 — plan the outfit, then obtain garment geometry."""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.errors import PlanningError
from wardrobe.pipeline.context import PipelineContext
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.providers import provider_for_mode


async def plan(context: PipelineContext) -> None:
    await context.emit(JobState.PLANNING, "planning the outfit")

    request = context.record.request.outfit
    outfit_plan = plan_outfit(request, context.catalog)

    context.plan = outfit_plan
    context.record.plan = outfit_plan
    for note in outfit_plan.notes:
        context.warn(note)

    await context.emit(
        JobState.PLANNING,
        f"planned '{outfit_plan.name}' ({outfit_plan.category}, {outfit_plan.silhouette})",
        templateId=outfit_plan.template_id,
        confidence=outfit_plan.confidence,
    )


async def generate(context: PipelineContext) -> None:
    await context.emit(JobState.GENERATING, "generating the garment")

    if context.plan is None:
        raise PlanningError("outfit planning must run before garment generation")

    provider = provider_for_mode(
        context.record.request.outfit.mode, context.settings, context.catalog
    )
    template = context.catalog.get(context.plan.template_id) if context.plan.template_id else None

    try:
        artifact = await provider.create(
            context.plan, template=template, analysis=context.record.analysis
        )
    finally:
        await provider.aclose()

    context.artifact = artifact
    await context.emit(
        JobState.GENERATING,
        f"garment ready from provider '{artifact.source}'",
        garmentId=artifact.id,
        provider=artifact.source,
    )


__all__ = ["plan", "generate"]
