"""BA1. What a caller may ask for: a tattoo, by design and placement, and nothing else.

Body art is an accessory to skin the finished outfit leaves visible
(docs/BODY_ART_PLAN.md). The request says what she would like; whether it is made
is decided after her clothes are built, from the skin they actually leave bare,
and a tattoo the clothes would hide is not made at all. Nothing here can ask for
clothing to change, and nothing a request says is read before the outfit is
assembled.

The request is a sibling of ``outfit`` on the job, not a field of it: the planner
copies ``OutfitRequest`` into every layer and set part (``plan_outfit_stack``), and
a tattoo list inside it would have been copied into each garment's request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Ratings a placement or a design at a placement can carry, weakest first. The
#: same three words packs use (wardrobe.targets.pack.RATINGS): a rating can only hide.
RATINGS = ("general", "swimwear", "intimate")


@dataclass(frozen=True)
class Placement:
    """A named place on her body. The frame itself is built from her bones (placement.py)."""

    id: str
    name: str
    rating: str
    #: Which way the Studio turns the viewer to show it: "back", "left", "right", "front".
    facing: str
    #: The body region it lies in, as the strip plan names regions.
    region: str


#: v1 placements (BA1-BA4). All seen in everyday clothes, so all general (plan §5);
#: the hip, rib, thigh and front placements come with BA9 and their own ratings.
PLACEMENTS: dict[str, Placement] = {
    p.id: p
    for p in (
        Placement("nape", "Nape of the neck", "general", "back", "upper"),
        Placement("upper-back", "Upper back", "general", "back", "upper"),
        Placement("left-shoulder-blade", "Left shoulder blade", "general", "back", "upper"),
        Placement("right-shoulder-blade", "Right shoulder blade", "general", "back", "upper"),
        Placement("spine-upper", "Upper spine", "general", "back", "upper"),
        Placement("spine-full", "Full spine", "general", "back", "upper"),
        Placement("lower-back", "Lower back", "general", "back", "lower"),
    )
}

#: At most this many tattoos in one job, one per placement.
MAX_ITEMS = 4

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def rating_rank(rating: str) -> int:
    return RATINGS.index(rating)


class BodyArtRequest(BaseModel):
    """One tattoo: a catalogue design at a placement, with its transforms."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    design: str = Field(min_length=1, max_length=64)
    placement: str
    #: Of the placement's default size.
    scale: float = Field(default=1.0, ge=0.5, le=1.5)
    #: Of the placement's width and height, from its centre.
    offset_u: float = Field(default=0.0, ge=-0.25, le=0.25, alias="offsetU")
    offset_v: float = Field(default=0.0, ge=-0.25, le=0.25, alias="offsetV")
    #: Degrees, in the plane of her skin.
    rotation: float = Field(default=0.0, ge=-30.0, le=30.0)
    opacity: float = Field(default=0.9, ge=0.3, le=1.0)
    #: sRGB hex; multiplies a design whose ink mode is "tint".
    ink: str = "#141414"
    mirror: bool = False

    @field_validator("placement")
    @classmethod
    def _known_placement(cls, value: str) -> str:
        if value not in PLACEMENTS:
            raise ValueError(f"placement {value!r} is not one of {sorted(PLACEMENTS)}")
        return value

    @field_validator("ink")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("ink is an sRGB hex colour, #rrggbb")
        return value.lower()

    def ink_rgb(self) -> tuple[float, float, float]:
        """The ink as sRGB 0..1."""
        return tuple(int(self.ink[i : i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def check_items(items: list[BodyArtRequest], remove: list[str]) -> None:
    """The list rules a single item cannot check. Raises ValueError."""
    if len(items) > MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} tattoos in one job")
    placements = [item.placement for item in items]
    if len(set(placements)) != len(placements):
        raise ValueError("one tattoo per placement")
    unknown = sorted(set(remove) - set(PLACEMENTS))
    if unknown:
        raise ValueError(f"bodyArtRemove names unknown placements {unknown}")
    both = sorted(set(remove) & set(placements))
    if both:
        raise ValueError(f"{both} both added and removed in one job")


__all__ = [
    "MAX_ITEMS",
    "PLACEMENTS",
    "RATINGS",
    "BodyArtRequest",
    "Placement",
    "check_items",
    "rating_rank",
]
