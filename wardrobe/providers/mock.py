"""Deterministic provider used by tests and by offline development."""

from __future__ import annotations

from hashlib import sha1

from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate
from wardrobe.domain.looks import OutfitPlan
from wardrobe.providers.base import GarmentProvider


class MockGarmentProvider(GarmentProvider):
    """Behaves like the template provider but never touches the catalogue."""

    name = "mock"
    produces_raw_mesh = False

    def __init__(self, *, coverage: list[str] | None = None) -> None:
        self.coverage = coverage or ["chest", "waist", "hips", "upperLegs"]
        self.calls: list[OutfitPlan] = []

    async def create(
        self,
        plan: OutfitPlan,
        *,
        template: GarmentTemplate | None = None,
        analysis: AvatarAnalysis | None = None,
    ) -> GarmentArtifact:
        self.calls.append(plan)
        digest = sha1(plan.name.encode("utf-8")).hexdigest()[:12]
        coverage = list(template.coverage) if template else list(self.coverage)
        return GarmentArtifact(
            id=f"garment_mock_{digest}",
            source=self.name,
            templateId=template.id if template else plan.template_id,
            proceduralKind=plan.category,
            coverage=coverage,
            anchors=list(template.anchors) if template else coverage,
            material=plan.material.to_dict(),
            metadata={"mock": True, "bodyClearanceMm": 6.0},
        )


__all__ = ["MockGarmentProvider"]
