"""Outfit requests, resolved plans, produced looks and fit reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from wardrobe.hosiery.options import HosieryOptions, HosieryPlan, RevealOptions, SuspenderBeltOptions


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
    # Style overrides — the same words the prompt can carry, as explicit choices.
    finish: str | None = None
    pattern: str | None = None
    #: 0..1; below 1 the fabric is see-through. Below the renderer's minimum (0.2)
    #: it is clamped, and the plan says so, rather than refused.
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage: str | None = None
    straps: str | None = None
    neckline: str | None = None
    #: A layered outfit: one request per garment, in any order — each is placed
    #: by its layer (foundation, legwear, main, one-piece, outer, shoes). Absent,
    #: the planner splits the prompt itself ("… + matching briefs under a … dress").
    layers: list[OutfitRequest] | None = Field(default=None, max_length=6)
    # Hosiery (wardrobe.hosiery): stockings, a suspender belt and how much of them the
    # hem shows. All optional; absent, the outfit plans exactly as it always did.
    hosiery: HosieryOptions | None = None
    suspender_belt: SuspenderBeltOptions | None = Field(default=None, alias="suspenderBelt")
    reveal: RevealOptions | None = None
    #: A named hosiery look (wardrobe.hosiery.presets); explicit fields above win over it.
    preset: str | None = Field(default=None, max_length=64)


class MaterialPlan(BaseModel):
    """Resolved surface appearance for the garment."""

    model_config = ConfigDict(populate_by_name=True)

    base_color: tuple[float, float, float, float] = Field(default=(0.5, 0.5, 0.5, 1.0), alias="baseColor")
    color_name: str | None = Field(default=None, alias="colorName")
    metallic: float = 0.0
    roughness: float = 0.7
    fabric: str | None = None
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: matte | satin | gloss | latex | metallic | sequin — see wardrobe.materials.finishes.
    finish: str = "matte"
    #: 1 is opaque; below it the fabric is see-through (alpha blended).
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    #: opaque | mask (holes: lace, fishnet) | blend (sheer).
    alpha_mode: str = Field(default="opaque", alias="alphaMode")
    #: none | lace | fishnet | sequin | stripes | dots | gingham
    pattern: str = "none"
    #: The pattern's second colour (stripes, dots, gingham), linear RGBA.
    pattern_color: tuple[float, float, float, float] | None = Field(default=None, alias="patternColor")
    #: Pattern tiles per metre of fabric; 0 without a pattern.
    texture_scale: float = Field(default=0.0, alias="textureScale")
    #: Lace over an opaque lining: the pattern shows, the body does not.
    lined: bool = False

    @property
    def exposes_body(self) -> bool:
        """Whether the body shows through the fabric: holes (lace, fishnet) or sheer."""
        return self.alpha_mode != "opaque" or self.opacity < 0.999

    def to_dict(self) -> dict:
        return {
            "baseColor": [round(c, 4) for c in self.base_color],
            "colorName": self.color_name,
            "metallic": round(self.metallic, 3),
            "roughness": round(self.roughness, 3),
            "fabric": self.fabric,
            "finish": self.finish,
            "opacity": round(self.opacity, 3),
            "alphaMode": self.alpha_mode,
            "pattern": self.pattern,
            "patternColor": [round(c, 4) for c in self.pattern_color] if self.pattern_color else None,
            "textureScale": self.texture_scale,
            "lined": self.lined,
        }


class StylePlan(BaseModel):
    """How much the garment covers and how it is cut — independent of what it is.

    A micro bikini is a bikini at ``coverage="micro"``, not a category of its
    own; a V-neck is an edge profile on whatever bodice the template builds.
    Every field's empty value means "as the template makes it", so a plan that
    names none of them builds exactly what it always built.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: full | standard | minimal | micro
    coverage: str = "standard"
    #: "" (the template's) | shoulder | halter | none | string | cross-back | garter | harness
    straps: str = ""
    #: "" | v | plunge | sweetheart | triangle (bikini cups)
    neckline: str = ""
    #: "" | low
    back: str = ""
    #: "" | high
    leg_cut: str = Field(default="", alias="legCut")
    #: "" | high | low — where briefs' waistband sits.
    rise: str = ""

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


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
    style: StylePlan = Field(default_factory=StylePlan)
    #: foundation | legwear | main | one-piece | outer | shoes — where it sits in a stack.
    role: str = "main"
    #: 1 (next to the body) .. 6 (outermost); inner layers are fitted first.
    layer: int = 3
    #: The garments of a layered outfit, inner first. Empty for one garment; when
    #: present, the fields above describe the outermost layer, so a client that
    #: knows nothing of layers still reads a sensible plan.
    layers: list[OutfitPlan] = Field(default_factory=list)
    #: Whether this garment, as it will render, needs an adult declaration: an
    #: intimate category, a template that says so, or fabric the body shows through.
    requires_adult: bool = Field(default=False, alias="requiresAdult")
    #: The outfit's hosiery design, on every garment that takes part in it: the belt,
    #: the stockings, the straps between them and the outer layer whose hem reveals them.
    hosiery: HosieryPlan | None = None
    #: Garments of one coordinated set share it ("matching set", a belt's matchingSetId).
    set_id: str | None = Field(default=None, alias="setId")
    #: Free-form keywords the planner recognised, for debugging and telemetry.
    keywords: list[str] = Field(default_factory=list)
    #: 0..1 — how much of the prompt the planner could actually account for.
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)

    @property
    def garments(self) -> list[OutfitPlan]:
        """Every garment to build, inner first: the layers, or this plan alone."""
        return list(self.layers) if self.layers else [self]

    def design_sheet(self, template=None, *, removed: list[str] | None = None,
                     inner: list[str] | None = None) -> dict:
        """The garment as a designer's specification: construction, material, fit, gate.

        ``template`` adds what only it knows (body conformity, clearance);
        ``removed`` and ``inner`` are the outfit's context — her garments taken
        off, and the layers already under this one.
        """
        material, style = self.material, self.style
        fit = template.fit if template is not None else None
        see_through = material.exposes_body
        if self.category in {"swimwear", "underwear"} and see_through:
            gate_reason = f"{self.category} in see-through fabric"
        elif self.category in {"swimwear", "underwear"}:
            gate_reason = self.category
        elif see_through:
            gate_reason = "see-through fabric: the body shows through"
        else:
            gate_reason = None
        risks = []
        if see_through:
            risks.append("what is under see-through fabric shows: inner layers and clearance matter more")
        if style.coverage in {"minimal", "micro"}:
            risks.append("narrow panels: widths are held at a 12 mm minimum")
        if fit is not None and fit.conform >= 0.9:
            risks.append("skin-tight: sits at clearance on the body or the layer beneath")
        if style.straps in {"string", "harness", "garter"}:
            risks.append("strap networks are separate pieces; check them in motion")
        return {
            "garment": self.name,
            "category": self.category,
            "template": self.template_id,
            "layer": self.layer,
            "role": self.role,
            "adultGateRequired": self.requires_adult,
            "adultGateReason": gate_reason,
            "coverage": style.coverage,
            "silhouette": self.silhouette,
            "hem": self.hem,
            "sleeve": self.sleeve,
            "neckline": style.neckline or "as cut",
            "back": style.back or "as cut",
            "legCut": style.leg_cut or "as cut",
            "rise": style.rise or "as cut",
            "straps": style.straps or "as cut",
            "baseColor": material.color_name,
            "fabric": material.fabric,
            "finish": material.finish,
            "opacity": material.opacity,
            "alphaMode": material.alpha_mode,
            "pattern": material.pattern,
            "patternScale": material.texture_scale,
            "lined": material.lined,
            "lining": "lined" if material.lined else "unlined" if see_through else "opaque fabric",
            "trim": "opaque straps and elastic" if see_through else "same as the fabric",
            "roughness": material.roughness,
            "metallic": material.metallic,
            "bodyConformity": fit.conform if fit is not None else None,
            "clearanceMm": fit.body_clearance_mm if fit is not None else None,
            "sourceGarmentsRemoved": list(removed or []),
            "innerLayersRetained": list(inner or []),
            "maskingPolicy": "none: the body under it stays visible" if see_through
            else "body under covered regions (Blender engine)",
            "fitRisks": risks,
            "fallback": [
                "no authored body under her clothes: that garment stays on, or the job is refused when "
                "underwear must sit there; nothing is generated",
                "a template that cannot be see-through renders opaque, and says so",
                "an avatar without MToon gets the same alpha and textures as glTF PBR",
            ],
        }

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
    #: Extra views of a hosiery look (thumb, detail, sit, walk, back): name -> URL. Absent otherwise.
    previews: dict[str, str] | None = None


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
    #: Worn clothing slots the garment replaced ("tops", "bottoms", …); empty when it layered.
    replaced_garments: list[str] = Field(default_factory=list, alias="replacedGarments")
    #: Base Body Prep: mode, what was taken off, and whether the body under it was complete.
    base_body: dict = Field(default_factory=dict, alias="baseBody")
    #: One entry per garment of a layered outfit, inner first: its own fit and clearance.
    layers: list[dict] = Field(default_factory=list)
    #: Stocking tops, clips, strap tension per pose and the reveal achieved (wardrobe.hosiery.report).
    hosiery: dict | None = None

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


# Self-referencing models (a request or plan made of layers of itself).
OutfitRequest.model_rebuild()
OutfitPlan.model_rebuild()
