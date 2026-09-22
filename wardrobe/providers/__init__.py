"""Garment providers and their registry."""

from __future__ import annotations

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitMode
from wardrobe.errors import ProviderError
from wardrobe.providers.base import GarmentProvider
from wardrobe.providers.mock import MockGarmentProvider
from wardrobe.providers.templates import TemplateGarmentProvider


def create_provider(name: str, settings: Settings, catalog: TemplateCatalog) -> GarmentProvider:
    """Instantiate a provider by name. Remote adapters import lazily."""
    key = (name or "template").lower()

    if key == "template":
        return TemplateGarmentProvider(catalog)
    if key == "mock":
        return MockGarmentProvider()
    if key == "meshy":
        from wardrobe.providers.meshy import MeshyProvider  # noqa: PLC0415 - optional path

        return MeshyProvider(settings)
    if key == "tripo":
        from wardrobe.providers.tripo import TripoProvider  # noqa: PLC0415 - optional path

        return TripoProvider(settings)

    raise ProviderError(f"unknown garment provider: {name!r}")


def provider_for_mode(
    mode: OutfitMode | str, settings: Settings, catalog: TemplateCatalog
) -> GarmentProvider:
    """Choose a provider for an outfit mode.

    ``auto`` and ``template`` use the template library. ``generated`` uses the
    configured AI provider, which is what ``WARDROBE_PROVIDER`` selects.
    """
    mode = OutfitMode(mode) if not isinstance(mode, OutfitMode) else mode
    if mode is OutfitMode.GENERATED:
        configured = settings.wardrobe_provider.lower()
        if configured in {"template", "mock"}:
            raise ProviderError(
                "outfit.mode='generated' requires WARDROBE_PROVIDER to name an AI "
                "mesh provider (meshy or tripo)"
            )
        return create_provider(configured, settings, catalog)

    if settings.wardrobe_provider.lower() == "mock":
        return MockGarmentProvider()
    return TemplateGarmentProvider(catalog)


__all__ = [
    "GarmentProvider",
    "TemplateGarmentProvider",
    "MockGarmentProvider",
    "create_provider",
    "provider_for_mode",
]
