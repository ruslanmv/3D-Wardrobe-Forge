"""Pattern blocks: the lingerie kinds, each built from its spec on her measured frame."""

from __future__ import annotations

from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters
from wardrobe.lingerie.blocks.frame import body_frame
from wardrobe.lingerie.specs import parse_block

#: The Studio's coverage words on a plain brief: the pattern they name. The legacy band brief
#: cut its leg line from them; the block keeps what they meant.
COVERAGE_PRESETS = {"minimal": "cheeky", "micro": "g-string"}
#: L5. The Studio's leg-cut word, on a plain cut: "high-leg bodysuit" is a high-leg one.
LEG_CUT_PRESETS = {"high": "high-leg"}
PLAIN_CUTS = ("classic", "cheeky", "bikini")


def build_block(kind: str, params: FitParameters) -> Mesh:
    """The garment for a lingerie ``kind`` (``wardrobe.lingerie.LINGERIE_KINDS``) at these measurements."""
    data = dict(params.metadata.get("lingerie") or {})
    coverage = COVERAGE_PRESETS.get(str(params.metadata.get("coverage") or ""))
    brief = dict(data.get("brief") or {})
    if kind in ("brief-block", "bodysuit-block") and coverage and brief.get("preset") == "classic":
        # Only a plain brief: a style that names its own cut (a tanga, a thong) keeps it.
        data["brief"] = {**brief, "preset": coverage}
    leg_cut = LEG_CUT_PRESETS.get(str(params.metadata.get("legCut") or ""))
    brief = dict(data.get("brief") or {})
    if kind in ("brief-block", "bodysuit-block") and leg_cut and brief.get("preset") in PLAIN_CUTS:
        data["brief"] = {**brief, "preset": leg_cut}
    block = parse_block(kind, data)
    rise = params.metadata.get("briefRise")
    if rise is not None and block.brief is not None:
        # P1. A look that places this brief against another garment's waistband sets its
        # rise; the template's own stays for every brief that nothing places.
        from dataclasses import replace

        block = replace(block, brief=replace(block.brief, rise=float(rise)))
    frame = body_frame(params)
    if kind == "brief-block":
        from wardrobe.lingerie.blocks.brief import build_brief

        mesh = build_brief(frame, block.brief, targets=whale_tail_targets(params))
    elif kind == "bra-block":
        from wardrobe.lingerie.blocks.bra import build_bra

        mesh = build_bra(frame, block.bra, block.straps)
    elif kind == "bodysuit-block":
        from wardrobe.lingerie.blocks.bodysuit import build_bodysuit

        mesh = build_bodysuit(frame, block.brief, block.bodysuit, block.straps)
    else:
        raise ValueError(f"no pattern block for {kind!r} yet")
    # What it was drafted on, for the fitting steps after the shell (wardrobe.lingerie.fit).
    meta = params.metadata
    mesh.metadata["lingerieFrame"] = {key: meta[key] for key in FRAME_KEYS if key in meta}
    return mesh


def whale_tail_targets(params: FitParameters):
    """P2. The brief's waistline against the jeans over it (the visible-thong block), or None.

    The jeans' top edge comes from the function the jeans are built with
    (``trouser_top`` and ``trouser_top_dip``) on the same body, so the thong is fitted to
    the jeans rather than placed on its own and hoped to meet them.
    """
    tail = params.metadata.get("whaleTail")
    if not isinstance(tail, dict):
        return None
    import math

    from wardrobe.geometry.procedural import trouser_top, trouser_top_dip
    from wardrobe.lingerie.blocks.brief import WaistlineTargets

    rise = str(tail.get("jeansRise") or "ultra-low")
    side = trouser_top(params, rise)
    height = params.height

    def jeans_top(phi):
        return side + trouser_top_dip(phi, rise, height)

    mm = 0.001
    return WaistlineTargets(
        side_y=float(jeans_top(math.pi / 2)) + float(tail.get("strapAboveMm", 38)) * mm,
        front_y=float(jeans_top(0.0)) - float(tail.get("frontBelowMm", 20)) * mm,
        back_y=float(jeans_top(math.pi)) + float(tail.get("backAboveMm", 18)) * mm,
        strap_m=float(tail.get("strapMm", 5)) * mm,
        jeans_top=jeans_top,
    )


#: Metadata a block is drafted from, carried with it.
FRAME_KEYS = ("lingerieLandmarks", "torsoProfile", "forward", "lingerie", "lowerBody", "whaleTail")


__all__ = ["FRAME_KEYS", "build_block"]
