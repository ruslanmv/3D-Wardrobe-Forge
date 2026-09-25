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


__all__ = ["hosiery_views", "run"]
