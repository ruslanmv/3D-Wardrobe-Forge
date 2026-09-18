from hashlib import sha1

from wardrobe.domain.garments import GarmentArtifact
from wardrobe.domain.jobs import OutfitRequest
from wardrobe.providers.base import GarmentProvider


class TemplateGarmentProvider(GarmentProvider):
    """Deterministic V1 provider using known garment topology."""

    CATEGORY_TO_TEMPLATE = {
        "dress": "assets/garment_templates/dresses/a-line.glb",
        "jacket": "assets/garment_templates/jackets/basic.glb",
        "top": "assets/garment_templates/tops/basic.glb",
        "skirt": "assets/garment_templates/skirts/basic.glb",
        "trousers": "assets/garment_templates/trousers/basic.glb",
    }

    async def create(self, outfit: OutfitRequest, *, avatar_analysis: dict) -> GarmentArtifact:
        prompt = outfit.prompt.lower()
        category = outfit.category or self._infer_category(prompt)
        mesh = self.CATEGORY_TO_TEMPLATE.get(category, self.CATEGORY_TO_TEMPLATE["dress"])
        digest = sha1(outfit.prompt.encode("utf-8")).hexdigest()[:12]
        return GarmentArtifact(
            id=f"garment_{digest}",
            source="template",
            mesh_path=mesh,
            material_metadata={
                "prompt": outfit.prompt,
                "category": category,
                "color": outfit.color,
                "style": outfit.style,
            },
        )

    def _infer_category(self, prompt: str) -> str:
        for candidate in ("jacket", "skirt", "trousers", "top", "dress"):
            if candidate in prompt:
                return candidate
        return "dress"
