"""Garment template model and catalogue loading.

A template is metadata first and geometry second: the metadata is what lets the
planner turn hundreds of prompts into a handful of robust, well-understood
garment shells.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

#: Body regions a template may declare coverage over.
COVERAGE_REGIONS = {
    "neck",
    "shoulders",
    "chest",
    "waist",
    "hips",
    "upperArms",
    "lowerArms",
    "upperLegs",
    "lowerLegs",
    "feet",
}

CATEGORIES = {
    "dress", "skirt", "top", "trousers", "jacket", "shoes",
    # try-on haul
    "shorts", "swimwear", "underwear", "nightwear", "legwear",
    # one garment, top to ankle: catsuits, unitards, jumpsuits
    "jumpsuit",
}

#: Shapes ``build_garment`` can make. A test holds this equal to the builder's own list,
#: so a template naming a shape that does not exist fails validation, not a job.
PROCEDURAL_KINDS = {
    "dress", "skirt", "top", "trousers", "jacket", "shoes",
    "crop-top", "tube-top", "bra", "briefs", "bikini", "one-piece", "swim-dress",
    "slip-dress", "shorts", "cropped-jacket", "legwear", "leggings", "catsuit",
}

#: Categories that only dress an avatar declared to depict an adult. See wardrobe.policy.intimate.
#: Not the whole gate: see-through fabric in any category needs the same declaration.
INTIMATE_CATEGORIES = frozenset({"swimwear", "underwear"})

#: Style vocabularies a template's fit policy and a plan's StylePlan may use.
COVERAGE_PRESETS: dict[str, float] = {"full": 1.12, "standard": 1.0, "minimal": 0.78, "micro": 0.58}
STRAP_PRESETS = ("shoulder", "halter", "none", "string", "cross-back", "garter", "harness")
NECKLINES = ("v", "plunge", "sweetheart", "triangle")
BACKS = ("low",)
LEG_CUTS = ("high",)


class FitPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    body_clearance_mm: float = Field(default=6.0, alias="bodyClearanceMm", ge=0.0, le=80.0)
    allow_length_scale: bool = Field(default=True, alias="allowLengthScale")
    allow_width_scale: bool = Field(default=True, alias="allowWidthScale")
    min_length_scale: float = Field(default=0.7, alias="minLengthScale", gt=0)
    max_length_scale: float = Field(default=1.3, alias="maxLengthScale", gt=0)
    #: 0..1 — how far the shell is drawn onto the body's actual surface after it is
    #: built. 0 keeps the measured shape; 1 is skin-tight (swimwear, underwear).
    conform: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Conform below the hip joint too. Off, a flared skirt keeps its flare.
    conform_below_hips: bool = Field(default=False, alias="conformBelowHips")
    #: One of STRAP_PRESETS; empty lets the shape choose.
    straps: str = ""
    #: Knife pleats round the skirt, 0 for none.
    pleats: int = Field(default=0, ge=0, le=32)
    #: Edge profiles the template is cut with by default; a plan may override each.
    neckline: str = ""
    back: str = ""
    leg_cut: str = Field(default="", alias="legCut")
    coverage: str = "standard"


class MaterialPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    supports_base_color: bool = Field(default=True, alias="supportsBaseColor")
    supports_pattern: bool = Field(default=True, alias="supportsPattern")
    supports_metallic: bool = Field(default=False, alias="supportsMetallic")
    #: Gloss, latex, satin, sequin: the toon highlight. Off, the garment stays matte.
    supports_finish: bool = Field(default=True, alias="supportsFinish")
    #: Sheer fabric and holed patterns (lace, fishnet). Off, the garment stays opaque.
    supports_transparency: bool = Field(default=True, alias="supportsTransparency")


class GarmentTemplate(BaseModel):
    """One robust garment geometry plus the rules for adapting it."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    id: str
    name: str
    category: str
    #: Either a GLB filename relative to the template, or ``procedural:<kind>``
    #: for a shell generated from the avatar's own measurements.
    mesh: str
    coverage: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    silhouette: str = "straight"
    hem: str = "knee"
    sleeve: str = "none"
    fit: FitPolicy = Field(default_factory=FitPolicy)
    materials: MaterialPolicy = Field(default_factory=MaterialPolicy)
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    #: Needs an adult declaration whatever its category or material.
    requires_adult: bool = Field(default=False, alias="requiresAdult")

    @property
    def is_procedural(self) -> bool:
        return self.mesh.startswith("procedural:")

    @property
    def procedural_kind(self) -> str:
        return self.mesh.split(":", 1)[1] if self.is_procedural else self.category

    def validate_semantics(self) -> list[str]:
        issues: list[str] = []
        if self.category not in CATEGORIES:
            issues.append(f"{self.id}: unknown category {self.category!r}")
        unknown_coverage = sorted(set(self.coverage) - COVERAGE_REGIONS)
        if unknown_coverage:
            issues.append(f"{self.id}: unknown coverage regions {unknown_coverage}")
        if not self.coverage:
            issues.append(f"{self.id}: template declares no coverage")
        if self.is_procedural and self.procedural_kind not in PROCEDURAL_KINDS:
            issues.append(f"{self.id}: unknown procedural shape {self.procedural_kind!r}")
        if self.fit.straps and self.fit.straps not in STRAP_PRESETS:
            issues.append(f"{self.id}: unknown strap style {self.fit.straps!r}")
        for field, value, allowed in (
            ("neckline", self.fit.neckline, NECKLINES),
            ("back", self.fit.back, BACKS),
            ("legCut", self.fit.leg_cut, LEG_CUTS),
        ):
            if value and value not in allowed:
                issues.append(f"{self.id}: unknown {field} {value!r}")
        if self.fit.coverage not in COVERAGE_PRESETS:
            issues.append(f"{self.id}: unknown coverage {self.fit.coverage!r}")
        # Sleeves are skinned to the bones the anchors name. Anchor a sleeved garment
        # to the chest alone and its sleeves bind to the torso: the avatar lowers her
        # arms and the sleeves stay out in a T. Jacket shapes always have long sleeves.
        sleeves = "long" if self.procedural_kind in {"jacket", "cropped-jacket"} else self.sleeve
        needed = {"short": {"upperArms"}, "long": {"upperArms", "lowerArms"}}.get(sleeves, set())
        if needed - set(self.anchors):
            issues.append(f"{self.id}: {sleeves} sleeves need anchors {sorted(needed - set(self.anchors))}")
        if self.fit.min_length_scale > self.fit.max_length_scale:
            issues.append(f"{self.id}: minLengthScale exceeds maxLengthScale")
        return issues


class GarmentArtifact(BaseModel):
    """A generated garment ready for fitting."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str  # template | meshy | tripo | mock
    template_id: str | None = Field(default=None, alias="templateId")
    mesh_path: str | None = Field(default=None, alias="meshPath")
    procedural_kind: str | None = Field(default=None, alias="proceduralKind")
    coverage: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    material: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class TemplateCatalog:
    """Loads and indexes ``*.json`` templates from the asset tree."""

    def __init__(self, templates: list[GarmentTemplate]) -> None:
        self._templates = {template.id: template for template in templates}

    @classmethod
    def from_directory(cls, root: str | Path) -> TemplateCatalog:
        root = Path(root)
        templates: list[GarmentTemplate] = []
        if root.exists():
            for path in sorted(root.rglob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}: invalid template JSON: {exc}") from exc
                templates.append(GarmentTemplate.model_validate(payload))
        return cls(templates)

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._templates)

    def __iter__(self):
        return iter(self._templates.values())

    def all(self) -> list[GarmentTemplate]:
        return list(self._templates.values())

    def get(self, template_id: str) -> GarmentTemplate | None:
        return self._templates.get(template_id)

    def by_category(self, category: str) -> list[GarmentTemplate]:
        return [t for t in self._templates.values() if t.category == category]

    def validate_all(self) -> list[str]:
        issues: list[str] = []
        for template in self._templates.values():
            issues.extend(template.validate_semantics())
        return issues


__all__ = [
    "SCHEMA_VERSION",
    "CATEGORIES",
    "COVERAGE_REGIONS",
    "FitPolicy",
    "MaterialPolicy",
    "GarmentTemplate",
    "GarmentArtifact",
    "TemplateCatalog",
]
