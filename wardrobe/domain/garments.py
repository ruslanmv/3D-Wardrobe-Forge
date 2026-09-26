"""Garment template model and catalogue loading.

A template is metadata first and geometry second: the metadata is what lets the
planner turn hundreds of prompts into a handful of robust, well-understood
garment shells.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from wardrobe.lingerie import LINGERIE_KINDS

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
    "slip-dress", "shorts", "cropped-jacket", "legwear", "leggings", "catsuit", "tights",
    "suspender-belt", "waspie", "guepiere", "slip-shorts",
} | set(LINGERIE_KINDS)

#: The template schema that carries a ``lingerie`` block (pattern blocks, wardrobe.lingerie).
LINGERIE_SCHEMA_VERSION = 2

#: Categories that only dress an avatar declared to depict an adult. See wardrobe.policy.intimate.
#: Not the whole gate: see-through fabric in any category needs the same declaration.
INTIMATE_CATEGORIES = frozenset({"swimwear", "underwear"})

#: Style vocabularies a template's fit policy and a plan's StylePlan may use.
COVERAGE_PRESETS: dict[str, float] = {"full": 1.12, "standard": 1.0, "minimal": 0.78, "micro": 0.58}
STRAP_PRESETS = ("shoulder", "halter", "none", "string", "cross-back", "garter", "harness")
NECKLINES = ("v", "plunge", "sweetheart", "triangle", "demi", "balconette")
RISES = ("high", "low")
BACKS = ("low",)
LEG_CUTS = ("high",)
FLARE_STARTS = ("waist", "high-hip", "hip", "below-hip")


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
    #: How deep the pleats fold, as a fraction of the skirt's radius each way. Absent: 0.03.
    pleat_depth: float | None = Field(default=None, alias="pleatDepth", ge=0.005, le=0.08)
    # The skirt's cut (wardrobe.geometry.procedural.SkirtShape); absent, the silhouette's.
    #: Hem half-width over the full hip's: 1.34 is an A-line a third wider at the hem.
    hem_flare_ratio: float | None = Field(default=None, alias="hemFlareRatio", ge=0.85, le=2.5)
    #: Where the flare begins: waist | high-hip | hip | below-hip.
    flare_start: str | None = Field(default=None, alias="flareStart")
    #: How the flare arrives: above 1 it starts gently and opens toward the hem.
    flare_power: float | None = Field(default=None, alias="flarePower", ge=0.5, le=4.0)
    waist_ease_mm: float | None = Field(default=None, alias="waistEaseMm", ge=0.0, le=60.0)
    hip_ease_mm: float | None = Field(default=None, alias="hipEaseMm", ge=0.0, le=80.0)
    #: Soft folds at the hem: how many round it, and how deep (fraction of the radius, each way).
    drape_folds: int = Field(default=0, alias="drapeFolds", ge=0, le=24)
    hem_drape: float = Field(default=0.0, alias="hemDrape", ge=0.0, le=0.08)
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
    #: The category's answer when a prompt names the category and nothing else ("skirt",
    #: "navy skirt", the Studio's "Planner chooses"), and the tie-break when two templates
    #: score the same. Without it the planner fell back on the template id's reverse
    #: alphabetical order, so a bare "skirt" was always skirt-pencil-v1 — the most
    #: tube-like cut in the catalogue, chosen by its file name. One per category.
    default_for_category: bool = Field(default=False, alias="defaultForCategory")
    #: Chosen from a prompt only when the prompt names one of its tags outright. Newer
    #: templates that overlap older ones use it, so a prompt that planned the older
    #: template still does: "suspender belt" is still the Garter Set.
    opt_in: bool = Field(default=False, alias="optIn")
    #: Schema 2 only: the pattern block a lingerie kind is built from — its spec
    #: (wardrobe.lingerie.specs), strap and elastic choices. Absent everywhere else.
    lingerie: dict | None = None

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
        if self.fit.flare_start and self.fit.flare_start not in FLARE_STARTS:
            issues.append(f"{self.id}: unknown flareStart {self.fit.flare_start!r}")
        if self.procedural_kind in LINGERIE_KINDS or self.lingerie is not None:
            if self.schema_version != LINGERIE_SCHEMA_VERSION:
                issues.append(f"{self.id}: a lingerie block needs schemaVersion {LINGERIE_SCHEMA_VERSION}")
            if self.procedural_kind in LINGERIE_KINDS and not self.lingerie:
                issues.append(f"{self.id}: {self.procedural_kind} needs a lingerie block")
            if self.lingerie is not None:
                from wardrobe.lingerie.specs import validate_block  # the spec lives with its builder

                found = validate_block(self.procedural_kind, self.lingerie)
                issues += [f"{self.id}: {issue}" for issue in found]
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

    def default_for(self, category: str) -> GarmentTemplate | None:
        """The template a bare ``category`` prompt gets (``defaultForCategory``), if one is declared."""
        return next((t for t in self.by_category(category) if t.default_for_category), None)

    def validate_all(self) -> list[str]:
        issues: list[str] = []
        for template in self._templates.values():
            issues.extend(template.validate_semantics())
        defaults: dict[str, list[str]] = {}
        for template in self._templates.values():
            if template.default_for_category:
                defaults.setdefault(template.category, []).append(template.id)
                if template.opt_in:
                    issues.append(f"{template.id}: an opt-in template cannot be its category's default")
        for category, ids in defaults.items():
            if len(ids) > 1:
                issues.append(f"{category}: more than one defaultForCategory template {sorted(ids)}")
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
