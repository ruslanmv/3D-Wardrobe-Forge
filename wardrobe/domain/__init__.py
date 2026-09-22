"""Pydantic domain models shared by the API, the pipeline and the worker."""

from wardrobe.domain.avatars import AvatarAnalysis, AvatarInput, LicenseAttestation
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate, TemplateCatalog
from wardrobe.domain.jobs import (
    CreateJobRequest,
    FailureReason,
    JobEvent,
    JobOptions,
    JobRecord,
    JobState,
)
from wardrobe.domain.looks import (
    ClippingCheck,
    FitReport,
    LookResult,
    MaterialPlan,
    OutfitMode,
    OutfitPlan,
    OutfitRequest,
)
from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest

__all__ = [
    "AvatarAnalysis",
    "AvatarInput",
    "LicenseAttestation",
    "GarmentArtifact",
    "GarmentTemplate",
    "TemplateCatalog",
    "CreateJobRequest",
    "FailureReason",
    "JobEvent",
    "JobOptions",
    "JobRecord",
    "JobState",
    "ClippingCheck",
    "FitReport",
    "LookResult",
    "MaterialPlan",
    "OutfitMode",
    "OutfitPlan",
    "OutfitRequest",
    "WardrobeLook",
    "WardrobeManifest",
]
