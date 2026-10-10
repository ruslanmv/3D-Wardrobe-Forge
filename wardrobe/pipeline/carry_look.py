"""Stage 3–8 of a tattoo-only job (BA6) — the look's own outfit, carried over untouched.

A job with ``bodyArt`` or ``bodyArtRemove`` and no ``outfit`` builds on a finished look and
changes nothing but its tattoos. It skips planning, base-body preparation, generation,
fitting and assembly — there is no garment to make — and takes the source document as the
assembled one. Only the root's provenance changes, so the new look is a look of its own:
its id, and ``baseLookId`` naming the look it was made from. Every garment node, mesh and
buffer byte is the source's (the I2 test compares them).

It refuses a source that is not a Forge look. Clothes come first (docs/BODY_ART_PLAN.md §0):
a tattoo is added to an outfit Forge finished, never straight onto an avatar as uploaded.
"""

from __future__ import annotations

from wardrobe.body_art.lifecycle import forge_tag
from wardrobe.domain.jobs import JobState
from wardrobe.errors import BodyArtNeedsLook, OutputInvalid
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.document import GltfDocument


async def run(context: PipelineContext) -> None:
    await context.emit(JobState.EXPORTING, "carrying the look's outfit over unchanged")
    if not context.source_bytes:
        raise OutputInvalid("there is no look to carry over")
    document = GltfDocument.from_bytes(context.source_bytes)
    tag = forge_tag(document.gltf)
    if tag is None or not tag.get("lookId"):
        raise BodyArtNeedsLook(
            "Body art goes on a finished look: dress her first, then add a tattoo to that look."
        )
    context.base_look_id = str(tag["lookId"])
    provenance = {k: v for k, v in tag.items() if k not in ("bodyArt", "bodyArtRemoved")}
    provenance.update(lookId=context.look_id, baseLookId=context.base_look_id)
    document.gltf["extras"]["wardrobeForge"] = provenance  # the recipes are rewritten by apply_body_art
    context.document = document
    context.output_bytes = document.to_bytes()
    if len(context.output_bytes) > context.settings.max_output_bytes:
        raise OutputInvalid("the look is over the output size limit")


__all__ = ["run"]
