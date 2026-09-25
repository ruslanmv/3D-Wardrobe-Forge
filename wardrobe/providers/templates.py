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
from wardrobe.hosiery.options import BELT_TEMPLATES
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

        style = plan.style
        key = (
            f"{template.id}|{plan.silhouette}|{plan.hem}|{plan.sleeve}|{plan.material.color_name}|"
            f"{plan.material.finish}|{plan.material.pattern}|{plan.material.opacity}|"
            f"{style.coverage}|{style.straps}|{style.neckline}|{style.back}|{style.leg_cut}|{style.rise}"
        )
        if plan.hosiery is not None:  # only then: every other garment keeps the id it always had
            key += "|" + plan.hosiery.model_dump_json(by_alias=True, exclude_none=True)
        digest = sha1(key.encode()).hexdigest()[:12]

        artifact = GarmentArtifact(
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
                "conform": template.fit.conform,
                "conformBelowHips": template.fit.conform_below_hips,
                "straps": style.straps or template.fit.straps,
                "pleats": template.fit.pleats,
                "coverage": style.coverage,
                "neckline": style.neckline,
                "back": style.back,
                "legCut": style.leg_cut,
                "rise": style.rise,
            },
        )
        # Hosiery: the outfit's design, and the belt's style, for the builders that read them.
        # Absent for every other garment, so their metadata is exactly what it was.
        if plan.hosiery is not None:
            artifact.metadata["hosiery"] = plan.hosiery.to_metadata()
            artifact.metadata["hosieryRole"] = plan.role
        if template.id in BELT_STYLE_OF_TEMPLATE:
            artifact.metadata["beltStyle"] = BELT_STYLE_OF_TEMPLATE[template.id]
        return artifact


#: Which belt style each hosiery belt template builds (wardrobe.hosiery.garter_belt).
BELT_STYLE_OF_TEMPLATE = {template: style for style, template in BELT_TEMPLATES.items()}

__all__ = ["TemplateGarmentProvider"]
