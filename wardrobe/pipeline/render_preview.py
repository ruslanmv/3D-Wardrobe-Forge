"""Stage 10 — render a preview image. Never fatal."""

from __future__ import annotations

import logging

from wardrobe.domain.jobs import JobState
from wardrobe.engines.base import FittingEngine
from wardrobe.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


async def run(context: PipelineContext, engine: FittingEngine) -> None:
    if not context.record.request.options.render_preview:
        return

    await context.emit(JobState.RENDERING, "rendering the preview")

    try:
        await engine.render_preview(context)
    except Exception as exc:  # a look without a thumbnail is still a good look
        logger.warning("preview rendering failed for %s: %s", context.job_id, exc)
        context.warn(f"preview rendering failed: {exc}")

    if context.plan is not None and context.plan.hosiery is not None and context.fit_report.hosiery:
        try:
            hosiery_views(context)
        except Exception as exc:  # the look is good without its extra views
            logger.warning("hosiery previews failed for %s: %s", context.job_id, exc)
            context.warn(f"hosiery previews failed: {exc}")

    if any(outcome.applied for outcome in context.body_art):
        try:
            body_art_views(context)
        except Exception as exc:  # the look is good without its back view
            logger.warning("body-art previews failed for %s: %s", context.job_id, exc)
            context.warn(f"{BACK_VIEW_MISSING} (it failed: {exc})")

    context.fit_report.preview_rendered = bool(context.preview_bytes)
    if not context.preview_bytes:
        context.warn("no preview image was produced")


def hosiery_views(context: PipelineContext) -> None:
    """Standing 3/4, the hem close-up, seated, walking and (seamed) back views, and a thumbnail."""
    from wardrobe.hosiery import previews
    from wardrobe.hosiery.fit import forward

    backend = context.record.request.options.preview_backend or context.settings.wardrobe_preview_backend
    facing = forward(context)
    views = previews.views_for(context.output_bytes, context.fit_report.hosiery, forward=facing,
                               pivots=context.measurements.bone_positions)
    images, used, note = previews.render_views(views, backend, forward=facing)
    if "preview" in images:
        context.preview_bytes = images["preview"]
        context.extra_previews["thumb.webp"] = previews.to_webp_resized(images["preview"], previews.THUMB)
    names = {"detail": "detail.webp", "sit": "preview-sit.webp", "walk": "preview-walk.webp",
             "back": "preview-back.webp"}
    for view, name in names.items():
        if view in images:
            context.extra_previews[name] = images[view]
    context.fit_report.hosiery["previews"] = {
        "backend": used, "requested": backend, "files": ["preview.webp", *sorted(context.extra_previews)],
        "note": note,
    }
    if note:
        context.warn(note)


#: BA5. Said whenever a look carries a back tattoo and its pictures show only her front.
BACK_VIEW_MISSING = (
    "The tattoo is on her back; this preview shows her front (the back view needs the web preview backend)."
)


def body_art_views(context: PipelineContext) -> None:
    """BA5. A look with a tattoo on her back is pictured from behind.

    Every v1 placement faces back, so the front preview of a tattooed look is a picture of
    exactly the part that did not change, and a look list of those thumbnails cannot tell a
    tattooed look from its base. The back view becomes ``preview.webp`` and the thumbnail;
    the front is kept beside it as ``preview-front.webp``.

    Only the web backend draws it. The native rasteriser paints each material one flat
    colour, so it would draw the decal as a rectangle of ink colour the size of her back —
    a worse lie than no back view at all. Without the web backend the front preview stays
    and the report says the tattoo is not in it.
    """
    from wardrobe.body_art.contract import PLACEMENTS
    from wardrobe.hosiery import previews

    if not any(
        outcome.applied and PLACEMENTS[outcome.request.placement].facing == "back"
        for outcome in context.body_art
    ):
        return
    backend = context.record.request.options.preview_backend or context.settings.wardrobe_preview_backend
    if backend not in {"web", "auto"} or not previews.web_available():
        context.warn(BACK_VIEW_MISSING)
        return
    view = {"name": "back", "vrm": context.output_bytes, "yaw": 180, "focus": None, "size": previews.PROFILE}
    back = previews.to_webp(previews.render_web([view])["back"])
    if context.preview_bytes:
        context.extra_previews["preview-front.webp"] = context.preview_bytes
    context.preview_bytes = back
    context.extra_previews["preview-back.webp"] = back
    context.extra_previews["thumb.webp"] = previews.to_webp_resized(back, previews.THUMB)


__all__ = ["BACK_VIEW_MISSING", "body_art_views", "hosiery_views", "run"]
