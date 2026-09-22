"""Fit the measured garment shell onto the real body surface.

The shell already matches the avatar's proportions. Blender's contribution is
accuracy: a shrinkwrap pass pulls it onto the actual mesh at a fixed offset, so
the garment follows anatomy the measurement model does not know about.
"""

from __future__ import annotations

import bpy


def shrinkwrap_to_body(garment, body, *, offset_m: float, smooth_iterations: int = 2) -> dict:
    """Project the garment onto the body surface, keeping ``offset_m`` clearance."""
    bpy.context.view_layer.objects.active = garment

    shrink = garment.modifiers.new(name="WardrobeShrinkwrap", type="SHRINKWRAP")
    shrink.target = body
    shrink.wrap_method = "NEAREST_SURFACEPOINT"
    shrink.offset = offset_m
    shrink.use_negative_direction = False
    shrink.use_positive_direction = True

    smooth = garment.modifiers.new(name="WardrobeSmooth", type="SMOOTH")
    smooth.factor = 0.4
    smooth.iterations = smooth_iterations

    applied = []
    for modifier in (shrink, smooth):
        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            applied.append(modifier.name)
        except RuntimeError as exc:
            garment.modifiers.remove(modifier)
            return {"applied": applied, "error": str(exc)}

    return {"applied": applied, "offsetM": offset_m}


def apply_scale_limits(garment, *, min_scale: float, max_scale: float) -> None:
    """Clamp any authored scale so a template cannot be stretched absurdly."""
    scale = list(garment.scale)
    garment.scale = tuple(max(min(value, max_scale), min_scale) for value in scale)


def coarse_align(garment, measurements: dict) -> None:
    """Centre the garment on the body's vertical axis before wrapping."""
    bounds = measurements.get("bounds")
    if not bounds:
        return
    (low_x, low_y, _), (high_x, high_y, _) = bounds[0], bounds[1]
    garment.location.x += (low_x + high_x) * 0.5 - garment.location.x
    garment.location.y += (low_y + high_y) * 0.5 - garment.location.y


__all__ = ["shrinkwrap_to_body", "apply_scale_limits", "coarse_align"]
