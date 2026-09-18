"""Template provider — the reliable production path.

It does not produce geometry itself: it resolves the plan to a template and
hands the fitting stage the parameters to build a shell at the avatar's own
measurements. That is what makes one template work across every body.
"""

from __future__ import annotations

from hashlib import sha1

from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate, TemplateCatalog
from wardrobe.domain.looks import OutfitPlan
from wardrobe.errors import PlanningError
from wardrobe.providers.base import GarmentProvider


class TemplateGarmentProvider(GarmentProvider):
    name = "template"
    produces_raw_mesh = False

    def __init__(self, catalog: TemplateCatalog) -> None:
        self.catalog = catalog

    async def create(
        self,
        plan: OutfitPlan,
        *,
        template: GarmentTemplate | None = None,
        analysis: AvatarAnalysis | None = None,
    ) -> GarmentArtifact:
        template = template or (self.catalog.get(plan.template_id) if plan.template_id else None)
        if template is None:
            candidates = self.catalog.by_category(plan.category)
            if not candidates:
                raise PlanningError(f"no template available for category {plan.category!r}")
            template = candidates[0]

        digest = sha1(
            f"{template.id}|{plan.silhouette}|{plan.hem}|{plan.sleeve}|{plan.material.color_name}".encode()
        ).hexdigest()[:12]

        return GarmentArtifact(
            id=f"garment_{digest}",
            source=self.name,
            templateId=template.id,
            meshPath=None if template.is_procedural else template.mesh,
            proceduralKind=template.procedural_kind if template.is_procedural else None,
            coverage=list(template.coverage),
            anchors=list(template.anchors),
            material=plan.material.to_dict(),
            metadata={
                "templateName": template.name,
                "silhouette": plan.silhouette,
                "hem": plan.hem,
                "sleeve": plan.sleeve,
                "bodyClearanceMm": template.fit.body_clearance_mm,
                "allowLengthScale": template.fit.allow_length_scale,
                "allowWidthScale": template.fit.allow_width_scale,
            },
        )


__all__ = ["TemplateGarmentProvider"]
