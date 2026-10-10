"""Stage 7b (BA4) — after the outfit is assembled: which requested tattoos her clothes leave room for.

Read-only. Clothes are finished when this runs; it measures the skin they leave visible
on the assembled VRM (both engines' output, her kept clothes included) and decides each
requested tattoo: gated, visible, projectable — or not, with the reason. A job that
asked for no body art, on a source that carries no tattoo recipe, returns after reading
only the source's JSON chunk (invariant I1).

BA6. The look a job builds on may carry tattoos of its own: their recipes are decided here
too, on the new outfit, so one the new clothes hide is dropped and one they bare again comes
back (``wardrobe.body_art.lifecycle``).
"""

from __future__ import annotations

import logging

from wardrobe.body_art.decorate import Outcome, decide
from wardrobe.body_art.lifecycle import inherited, live_placements
from wardrobe.domain.jobs import JobState
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.document import GltfDocument

logger = logging.getLogger(__name__)


def requested(context: PipelineContext) -> bool:
    request = context.record.request
    return bool(request.body_art or request.body_art_remove or context.body_art_inherited)


async def run(context: PipelineContext) -> None:
    request = context.record.request
    try:
        context.body_art_inherited = inherited(context.source_bytes, remove=list(request.body_art_remove))
    except Exception as exc:  # recipes that cannot be read are not guessed at; the outfit goes on
        logger.warning("body-art recipes unreadable for %s: %s", context.job_id, exc)
        context.body_art_inherited = []
    if not requested(context) or not context.output_bytes:
        return
    await context.emit(JobState.EXPORTING, "measuring the skin the outfit leaves visible")
    terms = context.info.license if context.info is not None else None
    try:
        document = GltfDocument.from_bytes(context.output_bytes)
        context.body_art = decide(
            document,
            list(request.body_art),
            context.body_art_catalog,
            depicts_adult=bool(request.avatar.depicts_adult),
            terms=terms,
            inherited=context.body_art_inherited,
            live=live_placements(document),
        )
    except Exception as exc:  # the outfit is the job: a tattoo that cannot be measured is not made
        logger.warning("body art could not be measured for %s: %s", context.job_id, exc)
        context.body_art = [
            Outcome(item, "general", reason=f"her skin could not be measured ({exc})", inherited=carried)
            for item, carried in [(i, False) for i in request.body_art]
            + [(i, True) for i in context.body_art_inherited]
        ]


__all__ = ["requested", "run"]
