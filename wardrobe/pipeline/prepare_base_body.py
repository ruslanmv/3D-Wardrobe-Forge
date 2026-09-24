"""Stage 3b — prepare the body the new outfit goes on: take off what it replaces, once.

Runs after planning (only the plan knows the outfit) and before any garment is
built (everything downstream must measure and fit against the body the outfit
will actually sit on). It generalises the single-garment replacement stage in
three ways:

* **The whole outfit decides.** The strip plan is computed over every layer
  together (``build_strip_plan``): bra + briefs + dress take off a one-piece
  that a bra alone never would.
* **The body is checked before anything comes off.** ``check_body`` samples the
  body as it would be without the garment. A region with no authored body
  under it is never exposed: that garment stays on, or — when the new outfit
  has to sit on the body there, as underwear does — the job is refused. Nothing
  is generated to fill a gap.
* **One transaction.** Stripping and dressing are the same job. The stripped
  state lives only in this job's working document; it is never stored, never
  previewed, and never the output — the source bytes are untouched and the
  output always carries the new outfit.

Modes (``options.baseBody``): ``preserve`` layers over what she wears;
``replace-outer`` takes off what the new outfit covers; ``underwear-base`` does
that and puts underwear on first (the planner adds a neutral foundation when
the outfit names none). There is no mode that outputs her with nothing on.
"""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.errors import BodyIncomplete
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
from wardrobe.vrm.measure import MeasurementError, measure_body


def layer_kinds(context: PipelineContext) -> list[tuple[str, str]]:
    """(shape kind, role) for every garment of the planned outfit."""
    kinds = []
    for plan in context.plan.garments:
        template = context.catalog.get(plan.template_id) if plan.template_id else None
        kinds.append((template.procedural_kind if template is not None else plan.category, plan.role))
    return kinds


async def run(context: PipelineContext) -> None:
    if context.plan is None or context.document is None or context.info is None:
        return
    mode = context.record.request.options.base_body_mode
    report = context.fit_report
    report.base_body = {"mode": mode, "removedSlots": [], "removedMaterials": [], "complete": None}
    if mode == "preserve":
        return

    inventory = garment_inventory(context.document)
    plan = build_strip_plan(inventory, layer_kinds(context))
    if not plan.remove:
        if inventory:
            worn = sorted({garment.slot for garment in inventory})
            context.warn(f"the new outfit layers over the worn {', '.join(worn)}")
        return

    # Check the body under each garment before taking any of it off.
    staying = {(g.mesh, g.primitive) for g in plan.retain}
    removing = list(plan.remove)
    body = context.measurements
    integrity = check_body(
        context.document, body, set().union(*(g.regions for g in removing)),
        without={(g.mesh, g.primitive) for g in removing}, also_without=staying,
    )
    missing = {region for region, check in integrity.regions.items() if not check.present}
    if missing:
        needs_body = mode == "underwear-base" or any(p.role == "foundation" for p in context.plan.garments)
        if needs_body:
            raise BodyIncomplete(
                "there is no authored body under this avatar's clothes at "
                f"{', '.join(sorted(missing))}; it cannot be undressed there, and nothing is generated "
                "in its place",
                detail={"missingRegions": sorted(missing), "integrity": integrity.to_dict()},
            )
        kept = [g for g in removing if g.regions & missing]
        removing = [g for g in removing if not (g.regions & missing)]
        context.warn(
            f"kept the worn {', '.join(sorted({g.slot for g in kept}))}: no body under it at "
            f"{', '.join(sorted(missing))}; the new outfit layers over it"
        )

    removed = remove_garments(context.document, removing)
    slots = list(dict.fromkeys(g.slot for g in removing))
    try:
        context.measurements = measure_body(context.document, context.info)
    except MeasurementError as exc:  # pragma: no cover - the bones did not change
        context.warn(f"re-measuring after undressing failed ({exc}); using the clothed measurements")

    report.replaced_garments = slots
    report.base_body.update(
        {
            "removedSlots": slots,
            "removedMaterials": removed,
            "complete": not missing,
            "integrity": integrity.to_dict(),
            "detectors": sorted({g.detector for g in removing}),
        }
    )
    await context.emit(JobState.PLANNING, f"replacing {', '.join(slots)}", replaced=slots, materials=removed)


__all__ = ["layer_kinds", "run"]
