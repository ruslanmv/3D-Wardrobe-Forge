"""Outfit requests, resolved plans, produced looks and fit reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OutfitMode(StrEnum):
    AUTO = "auto"
    TEMPLATE = "template"
    GENERATED = "generated"


class OutfitRequest(BaseModel):
    """What the caller asked for, in their own words."""

    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(min_length=2, max_length=1000)
    mode: OutfitMode = OutfitMode.AUTO
    #: Optional overrides that skip the corresponding part of prompt parsing.
    category: str | None = None
    color: str | None = None
    silhouette: str | None = None
    hem: str | None = None
    template_id: str | None = Field(default=None, alias="templateId")


class MaterialPlan(BaseModel):
    """Resolved surface appearance for the garment."""

    model_config = ConfigDict(populate_by_name=True)

    base_color: tuple[float, float, float, float] = Field(default=(0.5, 0.5, 0.5, 1.0), alias="baseColor")
    color_name: str | None = Field(default=None, alias="colorName")
    metallic: float = 0.0
    roughness: float = 0.7
    fabric: str | None = None
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict:
        return {
            "baseColor": [round(c, 4) for c in self.base_color],
            "colorName": self.color_name,
            "metallic": round(self.metallic, 3),
            "roughness": round(self.roughness, 3),
            "fabric": self.fabric,
        }


class OutfitPlan(BaseModel):
    """The planner's decision: which template, which shape, which material."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    category: str
    template_id: str | None = Field(default=None, alias="templateId")
    silhouette: str = "straight"
    hem: str = "knee"
    sleeve: str = "none"
    material: MaterialPlan = Field(default_factory=MaterialPlan)
    #: Free-form keywords the planner recognised, for debugging and telemetry.
    keywords: list[str] = Field(default_factory=list)
    #: 0..1 — how much of the prompt the planner could actually account for.
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)


class LookResult(BaseModel):
    """A finished, wearable derived VRM."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    type: Literal["vrmVariant"] = "vrmVariant"
    vrm_url: str = Field(alias="vrmUrl")
    preview_url: str | None = Field(default=None, alias="previewUrl")
    source_avatar_hash: str | None = Field(default=None, alias="sourceAvatarHash")
    prompt: str | None = None
    plan: OutfitPlan | None = None
    size_bytes: int | None = Field(default=None, alias="sizeBytes")


class ClippingCheck(StrEnum):
    PASSED = "passed"
    CLEARANCE_ONLY = "clearance-only"
    WARNINGS = "warnings"
    FAILED = "failed"
    NOT_RUN = "not-run"


class FitReport(BaseModel):
    """The acceptance record for a generated look.

    This is the artefact CI asserts on: 'Blender exited 0' is not a result,
    'the re-imported VRM still has a valid humanoid and weighted garment' is.
    """

    model_config = ConfigDict(populate_by_name=True)

    vrm_valid: bool = Field(default=False, alias="vrmValid")
    humanoid_valid: bool = Field(default=False, alias="humanoidValid")
    weights_valid: bool = Field(default=False, alias="weightsValid")
    expressions_preserved: bool = Field(default=False, alias="expressionsPreserved")
    skeleton_preserved: bool = Field(default=False, alias="skeletonPreserved")
    source_recoverable: bool = Field(default=False, alias="sourceRecoverable")
    clipping_check: ClippingCheck = Field(default=ClippingCheck.NOT_RUN, alias="clippingCheck")
    preview_rendered: bool = Field(default=False, alias="previewRendered")

    engine: str = "native"
    garment_vertices: int = Field(default=0, alias="garmentVertices")
    garment_triangles: int = Field(default=0, alias="garmentTriangles")
    bones_used: list[str] = Field(default_factory=list, alias="bonesUsed")
    measurements: dict = Field(default_factory=dict)
    coverage: dict = Field(default_factory=dict)
    pose_tests: dict = Field(default_factory=dict, alias="poseTests")
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.vrm_valid
            and self.humanoid_valid
            and self.weights_valid
            and self.skeleton_preserved
            and self.source_recoverable
            and self.clipping_check
            in {ClippingCheck.PASSED, ClippingCheck.CLEARANCE_ONLY, ClippingCheck.WARNINGS}
            and not self.errors
        )


__all__ = [
    "OutfitMode",
    "OutfitRequest",
    "MaterialPlan",
    "OutfitPlan",
    "LookResult",
    "ClippingCheck",
    "FitReport",
]
