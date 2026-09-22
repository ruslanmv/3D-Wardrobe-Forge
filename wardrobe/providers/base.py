"""Garment provider interface.

Everything that can produce garment geometry implements this: the template
library (production) and the AI mesh services (experimental). The pipeline
never branches on which one it got.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate
from wardrobe.domain.looks import OutfitPlan


class GarmentProvider(ABC):
    """Produce a garment for a planned outfit."""

    #: Stable identifier recorded on the artifact and in the fit report.
    name: str = "base"
    #: True when the provider returns an arbitrary mesh that must be cleaned,
    #: retopologised and fitted before it can be worn (Blender engine only).
    produces_raw_mesh: bool = False

    @abstractmethod
    async def create(
        self,
        plan: OutfitPlan,
        *,
        template: GarmentTemplate | None = None,
        analysis: AvatarAnalysis | None = None,
    ) -> GarmentArtifact:
        """Return an artifact describing the garment to fit."""

    async def aclose(self) -> None:  # noqa: B027
        """Release any network resources. Safe to call more than once.

        Concrete and empty on purpose: a local provider holds nothing open.
        """


__all__ = ["GarmentProvider"]
