"""PB1 — underwear ends up on bare skin, or the job is refused.

Runs once the outfit is fitted and assembled, because only then is it known what the
new garments cover. Base Body Prep has already taken off the garment meshes and
checked there is a body under them; what it cannot see is clothing painted into her
skin texture. AvatarSample B came out of a lingerie job with her lingerie over a
black crop top and black shorts — both painted on her skin — and the job reported
"fit passed": the meshes were right, the picture was not.

* The outfit she asked for is underwear or swimwear (``requested_foundation``) and her
  clothes were to come off (not ``preserve``): painted clothing left in view refuses
  the job. Nothing is repainted; another avatar, or keeping her clothes on, is the
  answer.
* Any other outfit: what shows is reported, as a warning. Those looks were never
  promised as bare skin, and refusing them would take away looks that work today.
* ``preserve``: the underwear was asked to go over her clothes. Reported, not refused.

The measurement is ``wardrobe.vrm.painted_clothing``; its result is kept in the fit
report (``baseBody.paintedSkin``) so a pass says what was checked.
"""

from __future__ import annotations

from wardrobe.errors import PaintedClothingShows
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import MeasurementError, measure_body
from wardrobe.vrm.painted_clothing import painted_skin


def _where(result) -> str:
    places = []
    if result.visible_upper:
        places.append("a top across her chest")
    if result.visible_lower:
        places.append("shorts or briefs at her hips")
    return " and ".join(places) or "her torso"


async def run(context: PipelineContext) -> None:
    if context.plan is None or not context.output_bytes:
        return
    report = context.fit_report
    mode = context.record.request.options.base_body_mode
    try:
        document = GltfDocument.from_bytes(context.output_bytes)
        # Measured on the output: a heel's stance lift moves her whole body up.
        measurements = measure_body(document, inspect_document(document))
    except (MeasurementError, ValueError, KeyError) as exc:  # pragma: no cover - validate_output says why
        context.warn(f"skin check skipped: the output could not be measured ({exc})")
        return
    garments = {(g.mesh, g.primitive) for g in garment_inventory(document)}
    result = painted_skin(document, measurements, garments)
    base_body = report.base_body if isinstance(report.base_body, dict) else {}
    if result is None:
        base_body["paintedSkin"] = {"checked": False, "why": "no textured skin to read"}
        report.base_body = base_body
        return
    base_body["paintedSkin"] = {"checked": True, **result.to_dict()}
    report.base_body = base_body
    if not result.shows:
        return

    share = f"{round(result.visible_share * 100)}%"
    if context.requested_foundation and mode != "preserve":
        base_body["layerOrder"] = "failed"
        kind = "swimwear" if any(g.category == "swimwear" for g in context.plan.garments) else "underwear"
        raise PaintedClothingShows(
            f"this avatar cannot wear {kind} as her innermost layer: clothing is painted on her skin "
            f"texture ({_where(result)}) and {share} of her torso would show it around or through the "
            f"{kind}. Her clothes came off, but painted clothing is part of her skin and is never repainted. "
            "Choose an avatar whose body is bare under her clothes (Model Girl is), or choose "
            "'Keep her clothes on' to style it over them",
            detail={"paintedSkin": result.to_dict()},
        )
    context.warn(f"clothing painted on her skin shows at {_where(result)} ({share} of her torso)")


__all__ = ["run"]
