from abc import ABC, abstractmethod

from wardrobe.domain.garments import GarmentArtifact
from wardrobe.domain.jobs import OutfitRequest


class GarmentProvider(ABC):
    @abstractmethod
    async def create(self, outfit: OutfitRequest, *, avatar_analysis: dict) -> GarmentArtifact:
        raise NotImplementedError
