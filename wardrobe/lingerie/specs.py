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


@dataclass(frozen=True)
class BriefSpec:
    """A brief's construction, as a pattern-maker specifies it.

    Heights are fractions of her crotch-to-waist span, so the same spec grades
    across bodies: ``rise`` 1.0 is at her natural waist, 0.5 halfway down.
    """

    #: Centre-front waistline height, as a fraction of crotch → waist.
    rise: float = 0.72
    #: How much higher the back waistline sits, same units: a back is cut higher.
    back_rise: float = 0.06
    #: Side panel height between waistband and leg opening, same units. A string is ~0.05.
    side_height: float = 0.42
    #: How far the front panel's leg line scoops toward the gusset: 0 straight, 1 deep.
    front_scoop: float = 0.55
    back_coverage: str = "full"
    #: Gusset widths at its front seam and at the crotch, and its length under her, in mm.
    gusset_front_width_mm: float = 70.0
    gusset_width_mm: float = 55.0
    gusset_length_mm: float = 150.0
    #: Elastic names from wardrobe.lingerie.elastic.ELASTICS.
    waist_elastic: str = "picot-10"
    leg_elastic: str = "picot-8"

    def __post_init__(self):
        if not 0.2 <= self.rise <= 1.15:
            raise ValueError(f"rise {self.rise} outside 0.2-1.15")
        if not 0.02 <= self.side_height <= 0.9:
            raise ValueError(f"sideHeight {self.side_height} outside 0.02-0.9")
        if self.back_coverage not in BACK_COVERAGES:
            raise ValueError(f"backCoverage {self.back_coverage!r} not one of {BACK_COVERAGES}")
        if not 20 <= self.gusset_width_mm <= 120 or not 20 <= self.gusset_front_width_mm <= 140:
            raise ValueError("gusset widths outside 20-140 mm")


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
    brief = _from_dict(BriefSpec, data.pop("brief", None), issues, "lingerie.brief")
    bra = _from_dict(BraSpec, data.pop("bra", None), issues, "lingerie.bra")
    straps = _from_dict(StrapBlock, data.pop("straps", None), issues, "lingerie.straps")
    fabric = data.pop("fabric", None)
    for key in data:
        issues.append(f"lingerie: unknown field {key!r}")
    return LingerieBlock(block=block, brief=brief, bra=bra, straps=straps, fabric=fabric,
                         issues=tuple(issues))


def validate_block(kind: str, data: dict) -> list[str]:
    return list(parse_block(kind, data).issues)


__all__ = ["BACK_COVERAGES", "BLOCK_OF_KIND", "BRA_STYLES", "BraSpec", "BriefSpec", "LingerieBlock",
           "StrapBlock", "parse_block", "validate_block"]
