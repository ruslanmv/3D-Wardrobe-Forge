"""Stage 3b — take off what the new garment replaces, then measure what is left.

Runs after planning, because only the plan knows the garment's category, and
before generation, because everything downstream must see the body the garment
will actually sit on. That second point is the reason this cannot be done at
assembly time: measurement takes the body's depth from the bounding box of all
geometry, and the native engine's clearance pass pushes the garment outside
everything present. Left in place, a VRoid hoodie would size a bikini to the
hoodie and hold it there, floating, after the hoodie was removed.

``options.replaceGarments = false`` keeps the old behaviour: layer over whatever
she is wearing.
"""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.garments import remove_slots, slots_replaced_by, worn_garments
from wardrobe.vrm.measure import MeasurementError, measure_body


async def run(context: PipelineContext) -> None:
    if context.plan is None or context.document is None or context.info is None:
        return
    if not context.record.request.options.replace_garments:
        return

    template = context.catalog.get(context.plan.template_id) if context.plan.template_id else None
    kind = template.procedural_kind if template is not None else context.plan.category
    worn = worn_garments(context.document)
    slots = slots_replaced_by(kind, worn)
    if not slots:
        if worn:
            layered = sorted({garment.slot for garment in worn})
            context.warn(f"{kind} layers over the worn {', '.join(layered)}")
        return

    try:
        removed = remove_slots(context.document, slots)
    except ValueError as exc:
        # A rig whose clothes share no mesh with the body: keep them and layer.
        context.warn(f"could not replace worn garments ({exc}); layering instead")
        return

    try:
        context.measurements = measure_body(context.document, context.info)
    except MeasurementError as exc:  # pragma: no cover - the bones did not change
        context.warn(f"re-measuring after replacement failed ({exc}); using the clothed measurements")

    context.fit_report.replaced_garments = slots
    await context.emit(
        JobState.PLANNING,
        f"replacing {', '.join(slots)}",
        replaced=slots,
        materials=removed,
    )


__all__ = ["run"]
