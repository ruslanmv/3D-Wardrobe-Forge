"""Fitting engine interface.

Two engines implement it:

* ``native`` — pure Python. Builds a parametric garment at the avatar's own
  measurements, binds it to the humanoid rig and writes the VRM directly.
  Deterministic, fast, and runnable in CI with no external binaries.
* ``blender`` — hands the same job to headless Blender, which can deform
  authored meshes, transfer weights from the body and delete covered polygons.

Both consume and produce the same :class:`~wardrobe.pipeline.context.PipelineContext`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from wardrobe.config import Settings
from wardrobe.pipeline.context import PipelineContext


class FittingEngine(ABC):
    name: str = "base"
    #: Whether this engine can consume arbitrary provider-generated meshes.
    supports_raw_mesh: bool = False
    #: Whether this engine can delete covered body polygons.
    supports_body_masking: bool = False

    @classmethod
    @abstractmethod
    def available(cls, settings: Settings) -> bool:
        """Whether this engine can run in the current environment."""

    @abstractmethod
    async def fit_garment(self, context: PipelineContext) -> None:
        """Produce fitted, skin-bound garment geometry on the context."""

    @abstractmethod
    async def assemble(self, context: PipelineContext) -> None:
        """Write the derived VRM into ``context.output_bytes``."""

    async def render_preview(self, context: PipelineContext) -> None:  # noqa: B027
        """Optionally set ``context.preview_bytes``. Never fatal.

        Deliberately concrete and empty: an engine that cannot render is
        still a valid engine.
        """


__all__ = ["FittingEngine"]
