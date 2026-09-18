from wardrobe.domain.garments import GarmentArtifact
from wardrobe.domain.jobs import OutfitRequest
from wardrobe.providers.base import GarmentProvider


class TripoProvider(GarmentProvider):
    """Future Tripo adapter."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def create(self, outfit: OutfitRequest, *, avatar_analysis: dict) -> GarmentArtifact:
        raise NotImplementedError("Tripo integration is not enabled in the scaffold")
