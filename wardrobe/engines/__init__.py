"""Fitting engine selection."""

from __future__ import annotations

import logging

from wardrobe.config import Settings
from wardrobe.engines.base import FittingEngine
from wardrobe.engines.blender import BlenderEngine
from wardrobe.engines.native import NativeEngine

logger = logging.getLogger(__name__)


def create_engine(name: str, settings: Settings) -> FittingEngine:
    """Resolve an engine name, honouring ``auto``.

    ``auto`` prefers Blender when the binary is present (it can do body masking
    and handle generated meshes) and falls back to the native engine otherwise.
    """
    key = (name or "auto").lower()

    if key == "native":
        return NativeEngine()
    if key == "blender":
        return BlenderEngine(settings)
    if key == "auto":
        if BlenderEngine.available(settings):
            return BlenderEngine(settings)
        logger.info("Blender not found (%s); using the native engine", settings.blender_bin)
        return NativeEngine()

    raise ValueError(f"unknown fitting engine: {name!r}")


def select_engine(context_engine: str, settings: Settings) -> FittingEngine:
    """Per-job override first, then the service default."""
    requested = (context_engine or "auto").lower()
    if requested == "auto":
        requested = settings.wardrobe_engine
    return create_engine(requested, settings)


__all__ = ["FittingEngine", "NativeEngine", "BlenderEngine", "create_engine", "select_engine"]
