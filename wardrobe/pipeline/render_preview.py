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

    context.fit_report.preview_rendered = bool(context.preview_bytes)
    if not context.preview_bytes:
        context.warn("no preview image was produced")


__all__ = ["run"]
