"""What a caller may ask of hosiery, a suspender belt and the reveal, and what that resolves to.

Every field is optional, and so is every block. An outfit request without a
``hosiery``, ``suspenderBelt`` or ``reveal`` block plans exactly as it did
before this module existed: nothing here is consulted.

Validation happens when the request is made, not halfway through a fit: an
unknown style or an out-of-range strap width is a 422 from the API, with the
field named, before anything is built. That is the stance ``garter_belt.py``
took (validate every option up front); an option that fails half a job later
has already cost an avatar download and a body measurement.

Snake case is accepted as well as the camelCase the rest of the API uses, so
``top_style`` and ``topStyle`` are the same field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ----------------------------------------------------------------------
# denier: the hosiery word for opacity
# ----------------------------------------------------------------------
#: Denier -> opacity (1 opaque), on the scale the planner's opacity words already use
#: (very sheer 0.35, transparent 0.45, sheer 0.55, translucent 0.7). 20 den gives 0.45,
#: the base alpha ``garter_belt.py`` settled on by eye (0.43). 60 den and above is
#: opaque, which matters beyond looks: an opaque stocking does not expose the body,
#: so it is the ungated form of the look (HOSIERY_PREVIEW §4).
DENIER_OPACITY: tuple[tuple[int, float], ...] = (
    (5, 0.24), (10, 0.30), (15, 0.38), (20, 0.45), (30, 0.55), (40, 0.68), (50, 0.82), (60, 1.0),
)

#: The deniers the Studio offers, and the ones the golden previews are checked at.
DENIER_STEPS = (10, 15, 20, 30, 40)


def denier_to_opacity(denier: float) -> float:
    """Piecewise-linear through ``DENIER_OPACITY``; clamped at both ends."""
    table = DENIER_OPACITY
    if denier <= table[0][0]:
        return table[0][1]
    for (d0, a0), (d1, a1) in zip(table, table[1:], strict=False):
        if denier <= d1:
            return round(a0 + (a1 - a0) * (denier - d0) / (d1 - d0), 3)
    return 1.0


# ----------------------------------------------------------------------
# request blocks
# ----------------------------------------------------------------------
HosieryType = Literal["thigh_high", "sheer", "opaque", "fishnet", "seamed"]
TopStyle = Literal["plain", "wide", "lace", "silicone"]
BeltStyle = Literal["classic", "high_waisted", "waspie", "guepiere"]
BeltMaterial = Literal["satin", "lace", "microfiber", "mesh"]
HardwareColour = Literal["silver", "gold", "black"]
Visibility = Literal["full", "hidden_under_skirt", "straps_only"]
RevealLevel = Literal["discreet", "glimpse", "statement"]


class _Options(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class BackSeamOptions(_Options):
    enabled: bool = False
    #: The seam line's width in millimetres.
    width: float = Field(default=2.5, ge=1.0, le=6.0)
    #: A colour word or #rrggbb; absent, a shade darker than the stocking.
    color: str | None = None


class HosieryOptions(_Options):
    """The stockings. ``type`` sets sensible defaults; every other field overrides them."""

    type: HosieryType = "sheer"
    #: 5–200. Mapped onto the opacity scale by ``denier_to_opacity``.
    denier: int | None = Field(default=None, ge=5, le=200)
    #: 0 (opaque) .. 0.8; wins over ``denier`` when both are given.
    transparency: float | None = Field(default=None, ge=0.0, le=0.8)
    color: str | None = None
    top_style: TopStyle = Field(default="plain", alias="topStyle")
    #: The stocking top's height; absent, the style's own (plain 3.5, wide and lace 5, silicone 2.5).
    top_width_cm: float | None = Field(default=None, alias="topWidthCm", ge=1.5, le=10.0)
    rolled_edge: bool = Field(default=True, alias="rolledEdge")
    back_seam: BackSeamOptions = Field(default_factory=BackSeamOptions, alias="backSeam")


class HardwareOptions(_Options):
    color: HardwareColour = "silver"
    clasp_enabled: bool = Field(default=True, alias="claspEnabled")
    adjuster_enabled: bool = Field(default=True, alias="adjusterEnabled")
    #: Absent, the belt style decides: rings on high-waisted belts, a guêpière and a waspie.
    ring_enabled: bool | None = Field(default=None, alias="ringEnabled")


class SuspenderBeltOptions(_Options):
    enabled: bool = True
    style: BeltStyle = "classic"
    color: str | None = None
    material: BeltMaterial = "satin"
    strap_count: Literal[4, 6] = Field(default=4, alias="strapCount")
    #: Absent, 9 mm scaled by her height over 1.6 m.
    strap_width_mm: float | None = Field(default=None, alias="strapWidthMm", ge=4.0, le=25.0)
    strap_thickness_mm: float = Field(default=1.2, alias="strapThicknessMm", ge=0.5, le=3.0)
    hardware: HardwareOptions = Field(default_factory=HardwareOptions)
    visibility: Visibility = "hidden_under_skirt"
    matching_set_id: str | None = Field(default=None, alias="matchingSetId", max_length=64)


class RevealOptions(_Options):
    level: RevealLevel = "glimpse"
    #: A hem word (mini, knee, midi, ankle, floor) or the skirt's length in centimetres
    #: below her natural waist. Given, it wins, and the report says what reveal it gives.
    explicit_hem_length: str | float | None = Field(default=None, alias="explicitHemLength")

    @field_validator("explicit_hem_length")
    @classmethod
    def _hem(cls, value):
        if value is None or isinstance(value, float | int):
            if value is not None and not 10.0 <= float(value) <= 140.0:
                raise ValueError("explicitHemLength in centimetres must be between 10 and 140")
            return value
        if value not in HEM_WORDS:
            raise ValueError(f"explicitHemLength must be one of {sorted(HEM_WORDS)} or centimetres")
        return value


HEM_WORDS = frozenset({"mini", "knee", "midi", "ankle", "floor"})


# ----------------------------------------------------------------------
# the resolved plan
# ----------------------------------------------------------------------
#: A stocking top's height by style, in metres (HOSIERY_PREVIEW §2.3).
TOP_WIDTH_M = {"plain": 0.035, "wide": 0.05, "lace": 0.05, "silicone": 0.025}

#: Belt template per style. New templates only: the Garter Set is never changed.
BELT_TEMPLATES = {
    "classic": "under-suspender-belt-v1",
    "high_waisted": "under-suspender-belt-high-v1",
    "waspie": "under-waspie-v1",
    "guepiere": "under-guepiere-v1",
}

#: Styles whose straps hang from rings by default.
RING_STYLES = frozenset({"high_waisted", "waspie", "guepiere"})

#: Colours the hardware kit comes in, as sRGB.
HARDWARE_COLOURS = {"silver": "#c7c9cc", "gold": "#c9a227", "black": "#1b1b1f"}

#: Stocking type -> defaults, before explicit fields apply.
TYPE_DEFAULTS: dict[str, dict] = {
    "thigh_high": {"denier": 20},
    "sheer": {"denier": 20},
    "opaque": {"denier": 80},
    "fishnet": {"denier": 60, "pattern": "fishnet"},
    "seamed": {"denier": 15, "seam": True},
}


class StockingPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = "sheer"
    denier: int = 20
    #: 1 is opaque; the base of the side-darkening falloff.
    opacity: float = 0.45
    pattern: str = "none"
    color: str = "#15151a"
    top_style: str = Field(default="plain", alias="topStyle")
    top_width_m: float = Field(default=0.035, alias="topWidthM")
    rolled_edge: bool = Field(default=True, alias="rolledEdge")
    seam: bool = False
    seam_width_m: float = Field(default=0.0025, alias="seamWidthM")
    seam_color: str | None = Field(default=None, alias="seamColor")


class BeltPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    style: str = "classic"
    template_id: str = Field(default="under-suspender-belt-v1", alias="templateId")
    color: str = "#111111"
    material: str = "satin"
    strap_count: int = Field(default=4, alias="strapCount")
    strap_width_m: float | None = Field(default=None, alias="strapWidthM")
    strap_thickness_m: float = Field(default=0.0012, alias="strapThicknessM")
    hardware_color: str = Field(default="silver", alias="hardwareColor")
    clasp: bool = True
    adjuster: bool = True
    ring: bool = False
    visibility: str = "hidden_under_skirt"


class RevealPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    level: str = "glimpse"
    explicit_hem_length: str | float | None = Field(default=None, alias="explicitHemLength")
    #: The hem word the prompt used for the outer garment, if any: kept as a range.
    prompt_hem: str | None = Field(default=None, alias="promptHem")


class HosieryPlan(BaseModel):
    """The whole hosiery design of an outfit. Present on every garment that takes part."""

    model_config = ConfigDict(populate_by_name=True)

    stockings: StockingPlan | None = None
    belt: BeltPlan | None = None
    reveal: RevealPlan | None = None
    set_id: str | None = Field(default=None, alias="setId")
    preset: str | None = None

    def to_metadata(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


__all__ = [
    "BELT_TEMPLATES",
    "BackSeamOptions",
    "BeltPlan",
    "DENIER_OPACITY",
    "DENIER_STEPS",
    "HARDWARE_COLOURS",
    "HEM_WORDS",
    "HardwareOptions",
    "HosieryOptions",
    "HosieryPlan",
    "RING_STYLES",
    "RevealOptions",
    "RevealPlan",
    "StockingPlan",
    "SuspenderBeltOptions",
    "TOP_WIDTH_M",
    "TYPE_DEFAULTS",
    "denier_to_opacity",
]
