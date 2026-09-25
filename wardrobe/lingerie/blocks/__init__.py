"""Pattern blocks: the lingerie kinds, each built from its spec on her measured frame."""

from __future__ import annotations

from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters
from wardrobe.lingerie.blocks.frame import body_frame
from wardrobe.lingerie.specs import parse_block


def build_block(kind: str, params: FitParameters) -> Mesh:
    """The garment for a lingerie ``kind`` (``wardrobe.lingerie.LINGERIE_KINDS``) at these measurements."""
    block = parse_block(kind, params.metadata.get("lingerie") or {})
    frame = body_frame(params)
    if kind == "brief-block":
        from wardrobe.lingerie.blocks.brief import build_brief

        mesh = build_brief(frame, block.brief)
    elif kind == "bra-block":
        from wardrobe.lingerie.blocks.bra import build_bra

        mesh = build_bra(frame, block.bra, block.straps)
    else:
        raise ValueError(f"no pattern block for {kind!r} yet")
    # What it was drafted on, for the fitting steps after the shell (wardrobe.lingerie.fit).
    meta = params.metadata
    mesh.metadata["lingerieFrame"] = {key: meta[key] for key in FRAME_KEYS if key in meta}
    return mesh


#: Metadata a block is drafted from, carried with it.
FRAME_KEYS = ("lingerieLandmarks", "torsoProfile", "forward", "lingerie")


__all__ = ["FRAME_KEYS", "build_block"]
