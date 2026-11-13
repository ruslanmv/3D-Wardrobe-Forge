"""PB6. The colours each catalog garment is prebuilt in (assets/catalog/palettes.json).

At most three per garment, the first its default: black, burgundy and champagne for lingerie;
black, wine and white for a mini dress; black, navy and sky for jeans. Category palettes are
the default and a garment may name another, so casual clothes are never forced into lingerie
colours. Every name is Forge's own colour vocabulary, so the planner builds exactly that colour.

Read once and checked on load: an unknown colour, a palette of more than three, or a garment
naming a palette that does not exist is a startup error with the offending entry named — a
typo here would otherwise prebuild hundreds of looks in the wrong colour.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from wardrobe.domain.garments import GarmentTemplate
from wardrobe.pipeline.plan_outfit import COLORS

PALETTE_FILE = Path(__file__).resolve().parents[2] / "assets" / "catalog" / "palettes.json"
MAX_COLOURS = 3
FALLBACK = ("black",)


class PaletteError(ValueError):
    pass


def check(data: dict) -> dict:
    palettes = data.get("palettes") or {}
    for name, colours in palettes.items():
        if not colours or len(colours) > MAX_COLOURS:
            count = len(colours or [])
            raise PaletteError(f"palette {name!r} must have 1-{MAX_COLOURS} colours, has {count}")
        if len(set(colours)) != len(colours):
            raise PaletteError(f"palette {name!r} repeats a colour: {colours}")
        unknown = [c for c in colours if c not in COLORS]
        if unknown:
            raise PaletteError(f"palette {name!r} uses colours Forge does not have: {unknown}")
    for where in ("categories", "templates"):
        for key, palette in (data.get(where) or {}).items():
            if palette not in palettes:
                raise PaletteError(f"{where}[{key!r}] names unknown palette {palette!r}")
    return data


@lru_cache(maxsize=1)
def load(path: str = str(PALETTE_FILE)) -> dict:
    return check(json.loads(Path(path).read_text(encoding="utf-8")))


def colours_for(template: GarmentTemplate, data: dict | None = None) -> list[str]:
    """The garment's prebuilt colours, default first. Black alone when nothing names it."""
    if not template.materials.supports_base_color:
        return []
    data = data or load()
    palette = (data.get("templates") or {}).get(template.id)
    palette = palette or (data.get("categories") or {}).get(template.category)
    return list((data.get("palettes") or {}).get(palette) or FALLBACK)


__all__ = ["PALETTE_FILE", "MAX_COLOURS", "PaletteError", "check", "load", "colours_for"]
