"""Stages 3 and 4 — plan the outfit, then obtain garment geometry."""

from __future__ import annotations

from wardrobe.domain.jobs import FailureReason, JobState
from wardrobe.errors import AdultDeclarationRequired, IntimateNotPermitted, PlanningError
from wardrobe.pipeline.context import PipelineContext
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.policy import intimate
from wardrobe.providers import provider_for_mode


async def plan(context: PipelineContext) -> None:
    await context.emit(JobState.PLANNING, "planning the outfit")

    request = context.record.request.outfit
    outfit_plan = plan_outfit(request, context.catalog)

    context.plan = outfit_plan
    context.record.plan = outfit_plan
    for note in outfit_plan.notes:
        context.warn(note)

    # Checked here, after planning, because only the plan knows the category — and
    # before anything is taken off or built, so a refusal changes nothing.
    # The gate follows what will render: an intimate category, a template that
    # says so, or fabric the body shows through (the plan's requiresAdult).
    decision = intimate.evaluate(
        outfit_plan.category,
        context.info.license if context.info is not None else None,
        depicts_adult=context.record.request.avatar.depicts_adult,
        requires_adult=outfit_plan.requires_adult,
        reason=intimate.gate_reason(outfit_plan.category, see_through=outfit_plan.material.exposes_body),
    )
    if not decision.allowed:
        error = (
            IntimateNotPermitted
            if decision.reason is FailureReason.INTIMATE_NOT_PERMITTED
            else AdultDeclarationRequired
        )
        raise error(
            decision.message,
            detail={"category": outfit_plan.category, "seeThrough": outfit_plan.material.exposes_body},
        )

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
