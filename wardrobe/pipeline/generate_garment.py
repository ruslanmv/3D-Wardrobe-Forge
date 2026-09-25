"""Stages 3 and 4 — plan the outfit, then obtain garment geometry."""

from __future__ import annotations

from wardrobe.domain.jobs import FailureReason, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.errors import AdultDeclarationRequired, IntimateNotPermitted, PlanningError
from wardrobe.hosiery.planning import connector_artifact
from wardrobe.pipeline.context import PipelineContext
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.policy import intimate
from wardrobe.providers import provider_for_mode

#: What underwear-base puts on when the outfit names no underwear: plain and
#: neutral, a foundation for the outer layers rather than a look of its own.
NEUTRAL_FOUNDATION = ("beige seamless bralette", "beige seamless briefs")


async def plan(context: PipelineContext) -> None:
    await context.emit(JobState.PLANNING, "planning the outfit")

    request = context.record.request.outfit
    outfit_plan = plan_outfit_stack(request, context.catalog)
    if context.record.request.options.base_body_mode == "underwear-base":
        outfit_plan = with_foundation(outfit_plan, request, context.catalog)

    context.plan = outfit_plan
    context.record.plan = outfit_plan
    for note in outfit_plan.notes:
        context.warn(note)

    # Checked here, after planning, because only the plan knows what each garment
    # is — and before anything is taken off or built, so a refusal changes
    # nothing. Every garment of a layered outfit must pass: one refused layer
    # refuses the outfit, rather than dressing her in the rest of it.
    for garment in outfit_plan.garments:
        decision = intimate.evaluate(
            garment.category,
            context.info.license if context.info is not None else None,
            depicts_adult=context.record.request.avatar.depicts_adult,
            requires_adult=garment.requires_adult,
            reason=intimate.gate_reason(garment.category, see_through=garment.material.exposes_body),
        )
        if not decision.allowed:
            error = (
                IntimateNotPermitted
                if decision.reason is FailureReason.INTIMATE_NOT_PERMITTED
                else AdultDeclarationRequired
            )
            raise error(
                decision.message,
                detail={
                    "category": garment.category,
                    "garment": garment.name,
                    "seeThrough": garment.material.exposes_body,
                },
            )

    await context.emit(
        JobState.PLANNING,
        f"planned '{outfit_plan.name}' ({outfit_plan.category}, {outfit_plan.silhouette})",
        templateId=outfit_plan.template_id,
        confidence=outfit_plan.confidence,
        layers=len(outfit_plan.garments),
    )


def with_foundation(outfit_plan, request, catalog):
    """Underwear-base: the outfit starts with underwear, a neutral pair if it names none."""
    if any(garment.role == "foundation" for garment in outfit_plan.garments):
        return outfit_plan
    layers = [OutfitRequest(prompt=prompt) for prompt in NEUTRAL_FOUNDATION]
    if request.layers:
        layers += list(request.layers)
    else:
        layers.append(request.model_copy(update={"layers": None}))
    return plan_outfit_stack(request.model_copy(update={"layers": layers}), catalog)


async def generate(context: PipelineContext) -> None:
    await context.emit(JobState.GENERATING, "generating the garment")

    if context.plan is None:
        raise PlanningError("outfit planning must run before garment generation")

    provider = provider_for_mode(
        context.record.request.outfit.mode, context.settings, context.catalog
    )
    context.artifacts = []
    try:
        for garment in context.plan.garments:
            if garment.role == "connector":  # suspender straps: no template, built from the fitted layers
                context.artifacts.append(connector_artifact(garment))
                continue
            template = context.catalog.get(garment.template_id) if garment.template_id else None
            context.artifacts.append(
                await provider.create(garment, template=template, analysis=context.record.analysis)
            )
    finally:
        await provider.aclose()

    artifact = context.artifacts[-1]
    context.artifact = artifact
    await context.emit(
        JobState.GENERATING,
        f"{len(context.artifacts)} garment(s) ready from provider '{artifact.source}'",
        garmentId=artifact.id,
        provider=artifact.source,
        garments=[a.id for a in context.artifacts],
    )


__all__ = ["NEUTRAL_FOUNDATION", "generate", "plan", "with_foundation"]
