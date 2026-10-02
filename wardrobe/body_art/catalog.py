"""BA1. The tattoo designs this deployment ships, and what each is rated where.

One manifest, ``assets/body_art/body-art.json``. A design names the placements it
is drawn for and the file its artwork is in; v1 artwork is vector paths authored
in this repository (``source: "vector"``), rasterised by our own code, so every
design is Apache-2.0 by construction and its pixels are reproducible.

BA5 adds ``source: "raster"``: a PNG whose alpha is the ink, installed only by
``tools/body_art/install_design.py``, which re-encodes it and records its licence and
origin beside it. Both kinds are drawn through ``raster.coverage``.

A design may *raise* a placement's rating (``rating: {"lower-back": "swimwear"}``)
but never lower it: the placement's rating is the floor, as a pack look's rating
can only hide.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from wardrobe.body_art.contract import PLACEMENTS, RATINGS, rating_rank

MANIFEST = "body-art.json"
INK_MODES = ("tint",)
SOURCES = ("vector", "raster")
#: What each source's artwork file ends in; ``raster.coverage`` reads by suffix.
SOURCE_SUFFIX = {"vector": ".json", "raster": ".png"}


class BodyArtDesign(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)
    name: str = Field(min_length=1, max_length=60)
    family: str = Field(min_length=1, max_length=60)
    placements: list[str] = Field(min_length=1)
    #: Width over height of the artwork, as it lies on her skin.
    aspect: float = Field(gt=0.1, le=10.0)
    ink_mode: str = Field(default="tint", alias="inkMode")
    source: str = "vector"
    #: The artwork, relative to the manifest.
    paths: str
    license: str
    #: Placement -> rating, where this design is stronger than the placement.
    rating: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class BodyArtCatalog:
    def __init__(self, designs: list[BodyArtDesign], root: Path | None = None):
        self.root = root
        self._designs = {design.id: design for design in designs}
        if len(self._designs) != len(designs):
            raise ValueError("duplicate body-art design ids")

    @classmethod
    def from_directory(cls, root: str | Path) -> BodyArtCatalog:
        root = Path(root)
        path = root / MANIFEST
        if not path.exists():
            return cls([], root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls([BodyArtDesign.model_validate(d) for d in payload.get("designs", [])], root)

    def __len__(self) -> int:
        return len(self._designs)

    def all(self) -> list[BodyArtDesign]:
        return list(self._designs.values())

    def get(self, design_id: str) -> BodyArtDesign | None:
        return self._designs.get(design_id)

    def for_placement(self, placement: str) -> list[BodyArtDesign]:
        return [d for d in self._designs.values() if placement in d.placements]

    def rating(self, design_id: str, placement: str) -> str:
        """The stronger of the placement's rating and the design's own there."""
        floor = PLACEMENTS[placement].rating
        own = self._designs[design_id].rating.get(placement, floor)
        return max(floor, own, key=rating_rank)

    def artwork_path(self, design: BodyArtDesign) -> Path:
        if self.root is None:
            raise ValueError("catalogue has no root")
        return self.root / design.paths

    def check(self, design_id: str, placement: str) -> str | None:
        """Why this design cannot go at this placement, or None."""
        design = self.get(design_id)
        if design is None:
            return f"no body-art design {design_id!r}"
        if placement not in design.placements:
            return f"{design.name} is drawn for {', '.join(design.placements)}, not {placement}"
        return None

    def validate_all(self) -> list[str]:
        issues: list[str] = []
        for design in self._designs.values():
            where = f"body art {design.id}"
            unknown = sorted(set(design.placements) - set(PLACEMENTS))
            if unknown:
                issues.append(f"{where}: unknown placements {unknown}")
            for placement, rating in design.rating.items():
                if rating not in RATINGS:
                    issues.append(f"{where}: rating {rating!r} at {placement} is not one of {RATINGS}")
                elif placement in PLACEMENTS and rating_rank(rating) < rating_rank(
                    PLACEMENTS[placement].rating
                ):
                    issues.append(f"{where}: a design cannot lower {placement}'s rating")
                if placement not in design.placements:
                    issues.append(f"{where}: rates {placement}, which it is not drawn for")
            if design.ink_mode not in INK_MODES:
                issues.append(f"{where}: ink mode {design.ink_mode!r} is not one of {INK_MODES}")
            if design.source not in SOURCES:
                issues.append(f"{where}: source {design.source!r} is not one of {SOURCES}")
            elif not design.paths.lower().endswith(SOURCE_SUFFIX[design.source]):
                # The loader picks by suffix; a raster entry pointing at paths (or the reverse)
                # would be drawn by the wrong reader, so the two must agree.
                suffix = SOURCE_SUFFIX[design.source]
                issues.append(f"{where}: a {design.source} design's artwork ends in {suffix}")
            if self.root is not None and not (self.root / design.paths).is_file():
                issues.append(f"{where}: artwork {design.paths} is missing")
            if not design.license:
                issues.append(f"{where}: no licence")
        return issues

    def to_public(self) -> dict:
        """What the Studio lists: placements and designs, no file paths."""
        return {
            "placements": [
                {"id": p.id, "name": p.name, "rating": p.rating, "facing": p.facing, "region": p.region}
                for p in PLACEMENTS.values()
            ],
            "designs": [
                {
                    "id": d.id,
                    "name": d.name,
                    "family": d.family,
                    "placements": d.placements,
                    "aspect": d.aspect,
                    "ratings": {p: self.rating(d.id, p) for p in d.placements if p in PLACEMENTS},
                    "description": d.description,
                    "license": d.license,
                }
                for d in self._designs.values()
            ],
        }


__all__ = ["BodyArtCatalog", "BodyArtDesign", "MANIFEST"]
