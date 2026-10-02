"""Stage 7c (BA4) — add the tattoos her finished outfit leaves room for, and say why any are not there.

Only appends to the assembled VRM (invariant I5); the one thing it ever takes off is an
earlier Forge tattoo it replaces or the request removes (I6). If adding them would put the
VRM over the size limit, or anything here fails, the outfit is delivered exactly as it was
assembled and the report says the tattoos were not added: the outfit is the job.
"""

from __future__ import annotations

import logging

from wardrobe.body_art.decorate import apply
from wardrobe.domain.jobs import JobState
from wardrobe.pipeline.analyze_exposed_skin import requested
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document

logger = logging.getLogger(__name__)


async def run(context: PipelineContext) -> None:
    if not requested(context) or not context.output_bytes:
        return
    outcomes = context.body_art
    request = context.record.request
    if any(o.decal is not None for o in outcomes) or request.body_art_remove:
        await context.emit(JobState.EXPORTING, "adding body art where her skin is visible")
        try:
            document = GltfDocument.from_bytes(context.output_bytes)
            apply(
                document,
                inspect_document(document),
                outcomes,
                context.body_art_catalog,
                list(request.body_art_remove),
            )
            data = document.to_bytes()
            if len(data) > context.settings.max_output_bytes:
                raise ValueError("adding it would put the VRM over the size limit")
            context.output_bytes = data
        except Exception as exc:
            logger.warning("body art not added for %s: %s", context.job_id, exc)
            for outcome in outcomes:
                if outcome.decal is not None:
                    outcome.applied, outcome.decal, outcome.reason = False, None, f"not added: {exc}"
    context.fit_report.body_art = [o.report() for o in outcomes]
    for outcome in outcomes:
        if not outcome.applied:
            context.warn(outcome.sentence)


__all__ = ["run"]
