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
from wardrobe.vrm.garment_inventory import garment_inventory

#: What underwear-base puts on when the outfit names no underwear: plain and
#: neutral, a foundation for the outer layers rather than a look of its own.
NEUTRAL_FOUNDATION = ("beige seamless bralette", "beige seamless briefs")

#: S2. What goes under a skirt that takes the place of her own bottoms. A VRoid body
#: under its shorts is not bare: the tights and undershorts of her original outfit
#: are painted on its skin up to the waist, so a new skirt over the removed shorts
#: showed the old outfit underneath. Slip shorts for every avatar — shorts, never
#: underwear, so no avatar needs a declaration to wear a skirt — and briefs instead
#: where the avatar is declared adult, which is what the Studio's private mode does.
SKIRT_LINER = "black slip shorts"
SKIRT_LINER_ADULT = "beige seamless briefs"
#: Outfits whose lower half is a skirt.
SKIRTED = frozenset({"skirt", "dress"})
#: Anything already on her hips under the skirt makes a liner redundant.
HIP_COVERING = frozenset({"underwear", "swimwear", "shorts", "trousers"})
HIP_COVERING_KINDS = frozenset({"tights", "leggings", "catsuit", "one-piece", "slip-shorts"})


async def plan(context: PipelineContext) -> None:
    await context.emit(JobState.PLANNING, "planning the outfit")

    request = context.record.request.outfit
    outfit_plan = plan_outfit_stack(request, context.catalog)
    mode = context.record.request.options.base_body_mode
    if mode == "underwear-base":
        outfit_plan = with_foundation(outfit_plan, request, context.catalog)
    elif mode == "replace-outer" and wears_her_own_bottoms(context):
        lined = with_skirt_liner(
            outfit_plan, request, context.catalog, depicts_adult=context.record.request.avatar.depicts_adult
        )
        if lined is not outfit_plan:
            liner = lined.garments[0].name.lower()
            context.warn(f"added {liner} under the skirt, in place of her own bottoms")
        outfit_plan = lined

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
    beneath = [OutfitRequest(prompt=prompt) for prompt in NEUTRAL_FOUNDATION]
    return plan_outfit_stack(request, catalog, beneath=beneath)


def wears_her_own_bottoms(context: PipelineContext) -> bool:
    """Whether she arrives in an outfit of her own below the waist — what a skirt then takes off.

    That is where the painted skin is. A body with nothing on (a calibration
    mannequin, an avatar authored bare) has only its skin under a skirt, and gets
    no liner it did not ask for.
    """
    if context.document is None:
        return False
    try:
        worn = garment_inventory(context.document)
    except Exception:  # an inventory failure must not fail the plan; no liner is the old behaviour
        return False
    return any(garment.role == "source" and "lower" in garment.regions for garment in worn)


def needs_skirt_liner(outfit_plan, catalog) -> bool:
    """A skirt, with nothing of the new outfit on her hips beneath it."""
    garments = outfit_plan.garments
    if not any(garment.category in SKIRTED for garment in garments):
        return False
    for garment in garments:
        template = catalog.get(garment.template_id) if garment.template_id else None
        kind = template.procedural_kind if template is not None else garment.category
        covering = garment.category in HIP_COVERING or kind in HIP_COVERING_KINDS
        if covering or garment.role in {"foundation", "liner"}:
            return False
    return True


def with_skirt_liner(outfit_plan, request, catalog, *, depicts_adult: bool):
    """S2. Put a liner under a skirt that replaces her bottoms; the plan unchanged when none is needed.

    Only in ``replace-outer``, and only when she wears bottoms of her own
    (``wears_her_own_bottoms``) — ``preserve`` keeps them under it and
    ``underwear-base`` brings its own briefs. The liner is the innermost layer
    and the request's overrides (colour, hem, ...) stay on the skirt.
    """
    if not needs_skirt_liner(outfit_plan, catalog):
        return outfit_plan
    liner = OutfitRequest(prompt=SKIRT_LINER_ADULT if depicts_adult else SKIRT_LINER)
    lined = plan_outfit_stack(request, catalog, beneath=[liner])
    # A liner the pipeline added is a liner, briefs included: as a "foundation"
    # it would make a job fail where there is no body under her clothes, and an
    # automatic addition must never turn a skirt that worked into a refusal.
    layers = [lined.layers[0].model_copy(update={"role": "liner"}), *lined.layers[1:]]
    return lined.model_copy(update={"layers": layers})


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


__all__ = [
    "NEUTRAL_FOUNDATION",
    "SKIRT_LINER",
    "generate",
    "needs_skirt_liner",
    "plan",
    "wears_her_own_bottoms",
    "with_foundation",
    "with_skirt_liner",
]
