"""L7. Fabric as a physical thing first, and what it looks like derived from that.

The material model the Forge renders with (``wardrobe.materials.finishes``) is visual
only: a finish, an opacity, an alpha mode, a pattern. Lace, fishnet and "sheer" shared
one vocabulary of how they look, and nothing said what they *are*: a powermesh band and
a tulle overlay were the same 55% blend; a fishnet's hole was a texture's tile, not a
size; a gusset was whatever the panel next to it was, sheer included.

Here a fabric is described the way a spec sheet describes it — construction, weight,
stretch, modulus, recovery, thickness, lining, and for an open fabric its hole — and
the visual plan is *derived* from that (:func:`derive_visual`):

    knit / woven   opaque; the finish from the fabric (satin, swim Lycra's sheen, matte jersey)
    mesh / tulle   a continuous blend, from how much of the area the yarn covers
    lace           the lace motif, as holes, or over a lining when it is lined
    net (fishnet)  the net texture at its own hole size, in millimetres of fabric

Nothing that existed changes: a ``MaterialPlan`` planned from words is still built
exactly as before (``finishes``), and this module is used where a block names a
fabric for a panel (:data:`PANEL_DEFAULTS`). The one rule it adds everywhere a block
has a gusset: **the gusset is lined and opaque**, under any sheer or lace request,
as every brief's gusset is (``gusset_material``).
"""

from __future__ import annotations

from dataclasses import dataclass

from wardrobe.materials.finishes import MIN_OPACITY, PATTERNS

CONSTRUCTIONS = ("knit", "woven", "mesh", "lace", "net", "elastic")


@dataclass(frozen=True)
class FabricSpec:
    """A fabric as a spec sheet gives it. Typical values for the class, not a mill's lot."""

    name: str
    construction: str
    weight_gsm: float
    #: Stretch at a standard load, percent, (warp, weft).
    stretch_pct: tuple[float, float]
    #: Newtons per metre of width to stretch it 10% (weft).
    modulus_n_per_m_at_10pct: float
    recovery_pct: float
    thickness_mm: float
    lining: bool = False
    #: Open fabrics: the hole's size across, millimetres (fishnet's diamond, a net's cell).
    hole_mm: float | None = None
    #: Share of the area the yarn covers, 0..1 (1 for a closed knit or weave).
    cover: float = 1.0
    #: How the surface catches light: matte | satin | gloss.
    sheen: str = "matte"

    def __post_init__(self) -> None:
        if self.construction not in CONSTRUCTIONS:
            raise ValueError(f"unknown construction {self.construction!r}")
        if not 0.0 < self.cover <= 1.0:
            raise ValueError("cover is a share of the area, 0..1")
        if self.construction == "net" and not self.hole_mm:
            raise ValueError("a net needs its hole size")


#: The starter library (LINGERIE_UPGRADE_PLAN L7).
FABRICS: dict[str, FabricSpec] = {spec.name: spec for spec in (
    FabricSpec("tricot", "knit", 110, (60, 120), 35, 92, 0.30),
    FabricSpec("powermesh", "mesh", 95, (80, 160), 60, 95, 0.35, cover=0.62),
    FabricSpec("stretch-lace", "lace", 120, (70, 140), 30, 90, 0.45),
    FabricSpec("galloon-lace", "lace", 140, (40, 90), 25, 88, 0.55),
    FabricSpec("tulle", "mesh", 25, (20, 60), 8, 70, 0.15, cover=0.38),
    FabricSpec("fishnet", "net", 60, (120, 200), 12, 85, 0.6, hole_mm=14.0, cover=0.25),
    FabricSpec("swim-lycra", "knit", 190, (90, 180), 70, 96, 0.55, sheen="satin"),
    FabricSpec("cotton-jersey", "knit", 160, (30, 60), 40, 85, 0.6, lining=True),
    FabricSpec("satin-woven", "woven", 95, (2, 4), 900, 99, 0.2, sheen="satin"),
)}


@dataclass(frozen=True)
class VisualSpec:
    """What the renderer needs, in ``MaterialPlan``'s terms."""

    finish: str
    opacity: float
    alpha_mode: str
    pattern: str
    texture_scale: float
    lined: bool

    def to_plan_fields(self) -> dict:
        return {"finish": self.finish, "opacity": self.opacity, "alphaMode": self.alpha_mode,
                "pattern": self.pattern, "textureScale": self.texture_scale, "lined": self.lined}


def derive_visual(spec: FabricSpec, *, lined: bool | None = None) -> VisualSpec:
    """The fabric's look, from what it is. ``lined`` overrides the spec's own lining."""
    lined = spec.lining if lined is None else lined
    finish = spec.sheen
    if spec.construction in ("knit", "woven", "elastic") or lined and spec.construction != "net":
        if spec.construction == "lace":
            # Lace over a lining: the motif shows, the body does not.
            return VisualSpec(finish, 1.0, "blend", "lace", _scale("lace"), True)
        return VisualSpec(finish, 1.0, "opaque", "none", 0.0, lined)
    if spec.construction == "mesh":
        opacity = max(MIN_OPACITY, round(spec.cover, 3))
        return VisualSpec(finish, opacity, "blend", "none", 0.0, False)
    if spec.construction == "lace":
        return VisualSpec(finish, 1.0, PATTERNS["lace"].alpha, "lace", _scale("lace"), False)
    # A net: the texture's tile is one diamond, drawn at the fabric's own hole size.
    return VisualSpec(finish, 1.0, PATTERNS["fishnet"].alpha, "fishnet", round(1000.0 / spec.hole_mm, 3),
                      False)


def _scale(pattern: str) -> float:
    return round(1.0 / PATTERNS[pattern].tile_m, 3)


#: Which fabric each panel of a block is cut from when nothing else is said.
PANEL_DEFAULTS: dict[str, dict[str, str]] = {
    "brief-block": {"panel": "tricot", "gusset": "cotton-jersey", "elastic": "tricot"},
    "bodysuit-block": {"panel": "tricot", "gusset": "cotton-jersey", "elastic": "tricot"},
    "bra-block": {"cup": "tricot", "band": "powermesh", "elastic": "tricot"},
    "swimwear": {"panel": "swim-lycra", "gusset": "swim-lycra"},
}


def panel_fabric(kind: str, panel: str) -> FabricSpec:
    table = PANEL_DEFAULTS.get(kind, PANEL_DEFAULTS["brief-block"])
    return FABRICS[table.get(panel, table.get("panel", "tricot"))]


def gusset_material(plan):
    """The gusset's MaterialPlan: the garment's colour, lined and opaque whatever its panels are."""
    visual = derive_visual(FABRICS["cotton-jersey"])
    return plan.model_copy(update={"opacity": visual.opacity, "alpha_mode": visual.alpha_mode,
                                   "pattern": visual.pattern, "texture_scale": visual.texture_scale,
                                   "lined": True, "fabric": "cotton-jersey"})


__all__ = ["CONSTRUCTIONS", "FABRICS", "PANEL_DEFAULTS", "FabricSpec", "VisualSpec", "derive_visual",
           "gusset_material", "panel_fabric"]
