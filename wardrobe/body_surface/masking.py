"""BS4. Whether her body may be hidden under a garment: by what the garment lets through.

The Blender engine can delete body polygons under a garment (``supports_body_masking``) — right
under opaque cloth, wrong under anything see-through, where her skin is exactly what shows.
Opacity is a rendering property, not a physical one, so the policy reads the garment's
*material*, never its category:

* ``BLEND`` (``alphaMode: "blend"``) or any opacity below 1 — sheer: **never** mask;
* ``MASK`` (lace, fishnet, cut-outs) — **alpha-aware**: only where the fabric is solid;
* ``OPAQUE`` — **opaque-only**: masking allowed.

The worker (``worker/blender/run_pipeline.py``) knows two words, ``none`` and ``body-only``.
It cannot test a lace texture's holes per body polygon, so alpha-aware goes to it as ``none``:
nothing is hidden that might show through a hole. That is what the engine already did
(``engines.blender.mask_policy``), now with the reason written down and a name for the day the
worker learns to read alpha.
"""

from __future__ import annotations

from wardrobe.body_surface.contract import BodyMaskPolicy


def body_mask_policy(material) -> BodyMaskPolicy:
    alpha = str(getattr(material, "alpha_mode", "opaque")).lower()
    opacity = float(getattr(material, "opacity", 1.0))
    if alpha == "blend" or (alpha == "opaque" and opacity < 0.999):
        return BodyMaskPolicy.NEVER
    if alpha == "mask":
        return BodyMaskPolicy.ALPHA_AWARE
    if alpha != "opaque":
        return BodyMaskPolicy.NEVER  # an alpha mode this module does not know: show her
    return BodyMaskPolicy.OPAQUE_ONLY


def worker_mask_policy(material) -> str:
    """The Blender worker's word for it: only opaque cloth may hide her body."""
    return "body-only" if body_mask_policy(material) is BodyMaskPolicy.OPAQUE_ONLY else "none"


__all__ = ["body_mask_policy", "worker_mask_policy"]
