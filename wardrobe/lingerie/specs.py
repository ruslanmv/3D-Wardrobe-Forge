"""The ``lingerie`` block of a schemaVersion 2 template: what a pattern block is built to.

A template names its block kind in ``mesh`` (``procedural:brief-block``) and
gives the construction here: the block's own spec, the straps, the elastics.
Values are the pattern-maker's, in millimetres or as fractions of a landmark
span, never "make it smaller": a high-leg brief is a brief with a higher side
height, not a brief scaled down.

Everything has a default, so ``{"block": "brief"}`` is a classic brief.
``validate_block`` is what the template catalogue runs, so a typo in a
template is a test failure, not a garment silently built to defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

import numpy as np

from wardrobe.lingerie.contract import StrapSpec

#: Which block each lingerie kind is built from.
BLOCK_OF_KIND = {"brief-block": "brief", "bra-block": "bra", "bikini-block": "bikini",
                 "bodysuit-block": "bodysuit"}
BACK_COVERAGES = ("full", "moderate", "cheeky", "thong")
BRA_STYLES = ("triangle", "balconette", "plunge", "full")
CLOSURES = ("back", "front", "none")


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _from_dict(cls, data: dict | None, issues: list[str], where: str):
    """Build a spec dataclass from camelCase keys; unknown keys and bad values are issues, defaults kept."""
    data = dict(data or {})
    known = {_camel(f.name): f for f in fields(cls)}
    values = {}
    for key, value in data.items():
        spec = known.get(key)
        if spec is None:
            issues.append(f"{where}: unknown field {key!r}")
            continue
        values[spec.name] = value
    try:
        return cls(**values)
    except (TypeError, ValueError) as error:
        issues.append(f"{where}: {error}")
        return cls()


#: Named rises: fractions of her crotch-to-waist span at centre front.
RISES = {"low": 0.5, "mid": 0.72, "high": 0.95, "high-waist": 1.05}
#: The legacy back-coverage words, as the fractions the grammar uses.
BACK_COVERAGE_WORDS = {"full": 0.85, "moderate": 0.65, "cheeky": 0.55, "thong": 0.12}
SIDE_TYPES = ("panel", "narrow", "string", "tie")


@dataclass(frozen=True)
class BriefSpec:
    """A bottom's construction as independent pattern rules, not as a style name.

    "String", "thong", "high-leg" and "bikini" are four different questions, and a
    brief that answered them with four meshes could not be a string bikini (string
    sides, a real back) without also being a thong. Here each is its own rule:

    * **rise** — where the waistline sits: a fraction of her crotch-to-waist span at
      centre front (or ``low`` / ``mid`` / ``high`` / ``high-waist``); ``back_rise``
      raises the back, as a back is cut higher.
    * **sides** — ``side_type`` (panel, narrow, string, tie) and ``side_width_mm``,
      the side seam's height between waistband and leg opening. A string is its
      elastic, 3–8 mm.
    * **leg cut** — ``leg_cut_height``: how high the leg opening rises at the side,
      as a fraction of crotch → waist. With the rise it fixes the side width; give
      one or the other. ``leg_extension_mm`` carries the leg opening down round the
      thigh (a boyshort).
    * **coverage** — ``front_coverage`` and ``back_coverage``, 0..1: how much of the
      panel's height, from waistline to the gusset seam, is covered across that
      half of her, averaged round her. The leg line's curve is *solved* so the
      pattern measures exactly this: 0.42 is 0.42 on any body.
    * **V-shaping** — ``front_v_depth``, ``back_v_depth``, 0..1: how far the waistline
      dips at centre front / centre back (a V-string's Y, a Brazilian's V back).
    * **gusset and back centre** — the gusset's widths and length, and
      ``back_center_width_mm``: how wide the back panel is where it meets the gusset
      (a thong's strip, a G-string's string).
    """

    rise: float | str = 0.72
    back_rise: float = 0.06
    side_type: str = "panel"
    side_width_mm: float | None = None
    leg_cut_height: float | None = None
    leg_extension_mm: float = 0.0
    front_coverage: float | None = None
    back_coverage: float | str = 0.85
    front_v_depth: float = 0.0
    back_v_depth: float = 0.0
    back_center_width_mm: float | None = None
    gusset_front_width_mm: float = 70.0
    gusset_width_mm: float = 55.0
    gusset_length_mm: float = 150.0
    #: Legacy (L3 templates): side height as a fraction of the span, and the front scoop.
    side_height: float | None = None
    front_scoop: float | None = None
    #: Elastic names from wardrobe.lingerie.elastic.ELASTICS.
    waist_elastic: str = "picot-10"
    leg_elastic: str = "picot-8"
    #: A named preset (BOTTOM_PRESETS) this spec starts from; set by ``parse_block``.
    preset: str | None = None

    def __post_init__(self):
        if isinstance(self.rise, str) and self.rise not in RISES:
            raise ValueError(f"rise {self.rise!r} not one of {tuple(RISES)} or a fraction")
        if not 0.2 <= self.rise_fraction <= 1.15:
            raise ValueError(f"rise {self.rise} outside 0.2-1.15")
        if self.side_type not in SIDE_TYPES:
            raise ValueError(f"sideType {self.side_type!r} not one of {SIDE_TYPES}")
        if self.side_width_mm is not None and not 2.0 <= self.side_width_mm <= 200.0:
            raise ValueError(f"sideWidthMm {self.side_width_mm} outside 2-200")
        if self.side_height is not None and not 0.02 <= self.side_height <= 0.9:
            raise ValueError(f"sideHeight {self.side_height} outside 0.02-0.9")
        if isinstance(self.back_coverage, str) and self.back_coverage not in BACK_COVERAGE_WORDS:
            raise ValueError(f"backCoverage {self.back_coverage!r} not one of {tuple(BACK_COVERAGE_WORDS)}")
        if not 0.0 <= self.back_fraction <= 1.0:
            raise ValueError(f"backCoverage {self.back_coverage} outside 0-1")
        if self.front_coverage is not None and not 0.0 <= self.front_coverage <= 1.0:
            raise ValueError(f"frontCoverage {self.front_coverage} outside 0-1")
        for name, value in (("frontVDepth", self.front_v_depth), ("backVDepth", self.back_v_depth)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} {value} outside 0-1")
        if self.leg_cut_height is not None and not 0.0 <= self.leg_cut_height <= 1.1:
            raise ValueError(f"legCutHeight {self.leg_cut_height} outside 0-1.1")
        if not 0.0 <= self.leg_extension_mm <= 150.0:
            raise ValueError(f"legExtensionMm {self.leg_extension_mm} outside 0-150")
        if not 20 <= self.gusset_width_mm <= 120 or not 20 <= self.gusset_front_width_mm <= 140:
            raise ValueError("gusset widths outside 20-140 mm")
        if self.back_center_width_mm is not None and not 2.0 <= self.back_center_width_mm <= 160.0:
            raise ValueError(f"backCenterWidthMm {self.back_center_width_mm} outside 2-160")

    @property
    def rise_fraction(self) -> float:
        return RISES[self.rise] if isinstance(self.rise, str) else float(self.rise)

    @property
    def back_fraction(self) -> float:
        value = self.back_coverage
        return BACK_COVERAGE_WORDS[value] if isinstance(value, str) else float(value)

    @property
    def front_fraction(self) -> float:
        """Front coverage; from the legacy scoop when only that is given (0.55 scoop ≈ 0.62)."""
        if self.front_coverage is not None:
            return float(self.front_coverage)
        scoop = 0.55 if self.front_scoop is None else float(self.front_scoop)
        return float(np.clip(0.9 - 0.5 * scoop, 0.2, 0.95))


#: The bottoms as presets over those rules. A template's ``brief`` block may name one
#: (``"preset": "cheeky"``) and override any field.
BOTTOM_PRESETS: dict[str, dict] = {
    "classic": {"rise": "mid", "sideWidthMm": 80, "backCoverage": 0.85, "frontCoverage": 0.75},
    "high-leg": {"rise": 0.8, "legCutHeight": 0.62, "backCoverage": 0.72, "frontCoverage": 0.6},
    "french-cut": {"rise": 0.85, "legCutHeight": 0.72, "backCoverage": 0.8, "frontCoverage": 0.6},
    "hipster": {"rise": "low", "sideWidthMm": 70, "backCoverage": 0.9, "frontCoverage": 0.85,
                "gussetFrontWidthMm": 80},
    # A boyshort's leg opening runs level round her thigh: cut at her crotch, not a side width.
    "boyshort": {"rise": "low", "legCutHeight": 0.02, "backCoverage": 0.95, "frontCoverage": 0.9,
                 "legExtensionMm": 45, "gussetFrontWidthMm": 90, "gussetWidthMm": 70},
    "high-waist": {"rise": "high-waist", "sideWidthMm": 130, "backCoverage": 0.9, "frontCoverage": 0.8},
    "bikini": {"rise": 0.6, "sideWidthMm": 45, "backCoverage": 0.68, "frontCoverage": 0.62},
    "cheeky": {"rise": "mid", "sideWidthMm": 38, "backCoverage": 0.58, "frontCoverage": 0.6},
    "brazilian": {"rise": "mid", "sideType": "narrow", "sideWidthMm": 26, "backCoverage": 0.42,
                  "backVDepth": 0.55, "frontCoverage": 0.55, "backCenterWidthMm": 60},
    "tanga": {"rise": "low", "sideType": "narrow", "sideWidthMm": 12, "backCoverage": 0.38,
              "frontCoverage": 0.5, "backCenterWidthMm": 45},
    "string-bikini": {"rise": 0.6, "sideType": "tie", "sideWidthMm": 6, "backCoverage": 0.6,
                      "frontCoverage": 0.6},
    "string": {"rise": 0.62, "sideType": "string", "sideWidthMm": 6, "backCoverage": 0.55,
               "frontCoverage": 0.55},
    "thong": {"rise": 0.66, "sideType": "narrow", "sideWidthMm": 18, "backCoverage": 0.12,
              "frontCoverage": 0.55, "backCenterWidthMm": 18, "gussetWidthMm": 40},
    "g-string": {"rise": 0.66, "sideType": "string", "sideWidthMm": 5, "backCoverage": 0.03,
                 "frontCoverage": 0.45, "backCenterWidthMm": 5, "gussetWidthMm": 35,
                 "gussetFrontWidthMm": 50},
    "v-string": {"rise": 0.7, "sideType": "string", "sideWidthMm": 5, "backCoverage": 0.03,
                 "frontCoverage": 0.45, "backCenterWidthMm": 5, "backVDepth": 0.6, "frontVDepth": 0.35,
                 "gussetWidthMm": 35, "gussetFrontWidthMm": 50},
    "high-waist-thong": {"rise": "high-waist", "sideType": "narrow", "sideWidthMm": 20,
                         "backCoverage": 0.1, "frontCoverage": 0.6, "backCenterWidthMm": 18,
                         "gussetWidthMm": 40},
}


@dataclass(frozen=True)
class BraSpec:
    """A bra's construction: cups on her bust points, gore on her sternum, band under the fold."""

    style: str = "triangle"
    #: Cup height above the bust point, and below it to the fold, as fractions of apex → fold.
    cup_height: float = 1.1
    #: How far the cup reaches across from the apex, as a fraction of apex → midline (inner) / side.
    cup_inner: float = 0.8
    cup_outer: float = 1.0
    cup_ease_mm: float = 2.0
    gore_height_mm: float = 25.0
    gore_width_mm: float = 14.0
    underband_width_mm: float = 12.0
    wing_height_mm: float = 30.0
    closure: str = "back"
    band_elastic: str = "band-12"

    def __post_init__(self):
        if self.style not in BRA_STYLES:
            raise ValueError(f"style {self.style!r} not one of {BRA_STYLES}")
        if self.closure not in CLOSURES:
            raise ValueError(f"closure {self.closure!r} not one of {CLOSURES}")
        if not 0.3 <= self.cup_height <= 2.5:
            raise ValueError(f"cupHeight {self.cup_height} outside 0.3-2.5")


@dataclass(frozen=True)
class StrapBlock:
    """The straps' make: ``ribbon`` flat straps (default) of this width and thickness."""

    profile: str = "ribbon"
    width_mm: float = 10.0
    thickness_mm: float = 1.2
    elastic: str = "strap-10"
    adjustable: bool = True
    style: str = "shoulder"

    def __post_init__(self):
        if self.profile != "ribbon":
            raise ValueError(f"strap profile {self.profile!r}: only 'ribbon' is built")
        if not 3.0 <= self.width_mm <= 25.0 or not 0.4 <= self.thickness_mm <= 2.5:
            raise ValueError("strap width 3-25 mm and thickness 0.4-2.5 mm")
        if self.style not in ("shoulder", "halter", "none"):
            raise ValueError(f"strap style {self.style!r}")

    def strap_spec(self, elastic=None) -> StrapSpec:
        return StrapSpec(width_m=self.width_mm / 1000.0, thickness_m=self.thickness_mm / 1000.0,
                         elastic=elastic, adjustable=self.adjustable)


@dataclass(frozen=True)
class LingerieBlock:
    block: str
    brief: BriefSpec = field(default_factory=BriefSpec)
    bra: BraSpec = field(default_factory=BraSpec)
    straps: StrapBlock = field(default_factory=StrapBlock)
    fabric: str | None = None
    issues: tuple[str, ...] = ()


def parse_block(kind: str, data: dict) -> LingerieBlock:
    """The template's block as specs, with every problem listed rather than raised."""
    issues: list[str] = []
    data = dict(data or {})
    block = str(data.pop("block", BLOCK_OF_KIND.get(kind, "")))
    if kind in BLOCK_OF_KIND and block != BLOCK_OF_KIND[kind]:
        issues.append(f"lingerie.block {block!r} does not match {kind} ({BLOCK_OF_KIND[kind]!r})")
    brief_data = dict(data.pop("brief", None) or {})
    preset = brief_data.get("preset")
    if preset is not None:
        if preset not in BOTTOM_PRESETS:
            issues.append(f"lingerie.brief: unknown preset {preset!r}")
        else:
            brief_data = {**{_camel(k) if "_" in k else k: v for k, v in BOTTOM_PRESETS[preset].items()},
                          **brief_data}
    brief = _from_dict(BriefSpec, brief_data, issues, "lingerie.brief")
    bra = _from_dict(BraSpec, data.pop("bra", None), issues, "lingerie.bra")
    straps = _from_dict(StrapBlock, data.pop("straps", None), issues, "lingerie.straps")
    fabric = data.pop("fabric", None)
    for key in data:
        issues.append(f"lingerie: unknown field {key!r}")
    return LingerieBlock(block=block, brief=brief, bra=bra, straps=straps, fabric=fabric,
                         issues=tuple(issues))


def validate_block(kind: str, data: dict) -> list[str]:
    return list(parse_block(kind, data).issues)


__all__ = [
    "BACK_COVERAGES", "BACK_COVERAGE_WORDS", "BLOCK_OF_KIND", "BOTTOM_PRESETS", "BRA_STYLES", "BraSpec",
    "BriefSpec", "LingerieBlock", "RISES", "SIDE_TYPES", "StrapBlock", "parse_block", "validate_block",
]
