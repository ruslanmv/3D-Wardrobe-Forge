"""Prompt -> outfit plan.

This is the deterministic styling engine: it reads a natural-language prompt
and resolves a category, silhouette, hem, sleeve length, fabric and colour,
then picks the template that best matches. No model call is required, which is
what makes the production path reproducible and testable.

``plan_with_llm`` is the extension point for an LLM-assisted planner: it only
ever *fills in* fields the rule-based pass could not resolve, so a model
outage degrades styling rather than breaking the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from wardrobe.domain.garments import GarmentTemplate, TemplateCatalog
from wardrobe.domain.looks import MaterialPlan, OutfitPlan, OutfitRequest
from wardrobe.errors import PlanningError

# ----------------------------------------------------------------------
# vocabulary
# ----------------------------------------------------------------------
COLORS: dict[str, str] = {
    "black": "#15151a",
    "white": "#f3f2ee",
    "ivory": "#f2e9dc",
    "cream": "#efe3cd",
    "grey": "#8a8a90",
    "gray": "#8a8a90",
    "charcoal": "#3a3c42",
    "silver": "#c8ccd2",
    "gold": "#c9a227",
    "red": "#b3202b",
    "crimson": "#a3162a",
    "burgundy": "#6d1a2d",
    "maroon": "#5c1a24",
    "wine": "#6b1f34",
    "pink": "#e59ab8",
    "rose": "#d98294",
    "blush": "#efc2c4",
    "coral": "#e4715c",
    "orange": "#d9772f",
    "peach": "#f0b08a",
    "yellow": "#e3c341",
    "mustard": "#c39b26",
    "green": "#3f7a4f",
    "emerald": "#1f7a55",
    "olive": "#6b6b3a",
    "mint": "#a9d8c2",
    "teal": "#237c7f",
    "turquoise": "#35a8a5",
    "blue": "#2f5fa8",
    "navy": "#1e2a4d",
    "cobalt": "#2b4fbd",
    "sky": "#8fb8de",
    "purple": "#6b3f9e",
    "violet": "#7a4fb0",
    "lavender": "#c3aede",
    "plum": "#5d2e50",
    "brown": "#6b4a32",
    "tan": "#b08c62",
    "beige": "#ddccb0",
    "khaki": "#a89968",
}

#: fabric -> (roughness, metallic, note)
FABRICS: dict[str, tuple[float, float]] = {
    "satin": (0.22, 0.04),
    "silk": (0.28, 0.02),
    "velvet": (0.85, 0.0),
    "leather": (0.42, 0.0),
    "denim": (0.88, 0.0),
    "cotton": (0.82, 0.0),
    "linen": (0.86, 0.0),
    "wool": (0.9, 0.0),
    "knit": (0.92, 0.0),
    "chiffon": (0.55, 0.0),
    "lace": (0.6, 0.0),
    "sequin": (0.18, 0.55),
    "sequined": (0.18, 0.55),
    "metallic": (0.2, 0.8),
    "latex": (0.15, 0.05),
    "tweed": (0.93, 0.0),
    "corduroy": (0.9, 0.0),
}

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dress": ("dress", "gown", "frock", "sundress"),
    "skirt": ("skirt",),
    "jacket": ("jacket", "blazer", "coat", "parka", "cardigan"),
    "trousers": ("trousers", "pants", "jeans", "slacks", "chinos", "leggings"),
    "top": ("top", "shirt", "blouse", "tee", "t-shirt", "sweater", "hoodie", "jumper"),
    "shoes": ("shoes", "boots", "heels", "sneakers", "trainers", "sandals"),
}

SILHOUETTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "a-line": ("a-line", "a line", "flared"),
    "fit-and-flare": ("fit and flare", "fit-and-flare", "skater"),
    "cocktail": ("cocktail", "party"),
    "sheath": ("sheath", "bodycon", "fitted", "column"),
    "pencil": ("pencil", "straight-cut"),
    "ball-gown": ("ball gown", "ballgown", "princess"),
    "wide": ("wide", "wide-leg", "palazzo", "flowy"),
    "slim": ("slim", "skinny", "tapered"),
    "oversized": ("oversized", "baggy", "loose", "relaxed"),
    "straight": ("straight", "classic", "regular"),
}

HEM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mini": ("mini", "short", "above the knee"),
    "knee": ("knee", "knee-length", "midi-short"),
    "midi": ("midi", "calf", "tea-length"),
    "ankle": ("ankle", "ankle-length"),
    "floor": ("floor", "full-length", "maxi", "long gown", "train"),
}

SLEEVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "none": ("sleeveless", "strapless", "tank", "camisole", "halter"),
    "short": ("short sleeve", "short-sleeved", "cap sleeve", "t-shirt", "tee"),
    "long": ("long sleeve", "long-sleeved", "full sleeve"),
}

#: Words that imply a dressy register when no explicit silhouette is given.
FORMALITY_KEYWORDS = {
    "formal": ("elegant", "evening", "formal", "gala", "black-tie", "sophisticated", "date-night"),
    "casual": ("casual", "cozy", "everyday", "relaxed", "comfy", "weekend", "sunday"),
    "sporty": ("sport", "sporty", "athletic", "gym", "running"),
}


@dataclass(slots=True)
class ParsedPrompt:
    category: str | None = None
    color_name: str | None = None
    color_hex: str | None = None
    fabric: str | None = None
    silhouette: str | None = None
    hem: str | None = None
    sleeve: str | None = None
    formality: str | None = None
    matched: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.matched is None:
            self.matched = []


# ----------------------------------------------------------------------
# colour helpers
# ----------------------------------------------------------------------
def srgb_to_linear(channel: float) -> float:
    """glTF baseColorFactor is linear; prompt colours are authored as sRGB."""
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def hex_to_linear_rgba(value: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"invalid hex colour: {value!r}")
    channels = [int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    r, g, b = (srgb_to_linear(c) for c in channels)
    return (round(r, 5), round(g, 5), round(b, 5), alpha)


# ----------------------------------------------------------------------
# parsing
# ----------------------------------------------------------------------
def _find(text: str, table: dict[str, tuple[str, ...]]) -> tuple[str | None, list[str]]:
    """Longest-phrase-wins lookup so 'long sleeve' beats 'long'."""
    best: tuple[str, str] | None = None
    for key, phrases in table.items():
        for phrase in phrases:
            matched = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
            if matched and (best is None or len(phrase) > len(best[1])):
                best = (key, phrase)
    return (best[0], [best[1]]) if best else (None, [])


def parse_prompt(prompt: str) -> ParsedPrompt:
    text = prompt.lower().strip()
    parsed = ParsedPrompt()

    parsed.category, matched = _find(text, CATEGORY_KEYWORDS)
    parsed.matched.extend(matched)

    parsed.silhouette, matched = _find(text, SILHOUETTE_KEYWORDS)
    parsed.matched.extend(matched)

    parsed.hem, matched = _find(text, HEM_KEYWORDS)
    parsed.matched.extend(matched)

    parsed.sleeve, matched = _find(text, SLEEVE_KEYWORDS)
    parsed.matched.extend(matched)

    parsed.formality, matched = _find(text, FORMALITY_KEYWORDS)
    parsed.matched.extend(matched)

    # Colour: take the earliest mention, and the longest name at that position.
    # 'navy blue' is navy; 'blue denim jacket' is blue.
    matches: list[tuple[int, int, str]] = []
    for name in COLORS:
        found = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)
        if found:
            matches.append((found.start(), -len(name), name))
    if matches:
        _, _, name = min(matches)
        parsed.color_name = name
        parsed.color_hex = COLORS[name]
        parsed.matched.append(name)

    for fabric in sorted(FABRICS, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(fabric)}(?!\w)", text):
            parsed.fabric = fabric
            parsed.matched.append(fabric)
            break

    return parsed


def _shade(rgba: tuple[float, float, float, float], text: str) -> tuple[float, float, float, float]:
    """Apply 'dark' / 'light' / 'pale' / 'deep' modifiers to a colour."""
    factor = 1.0
    if re.search(r"(?<!\w)(dark|deep|rich)(?!\w)", text):
        factor = 0.55
    elif re.search(r"(?<!\w)(light|pale|soft|pastel)(?!\w)", text):
        factor = 1.0  # lighten towards white instead of scaling up
        r, g, b, a = rgba
        return (
            round(r + (1.0 - r) * 0.45, 5),
            round(g + (1.0 - g) * 0.45, 5),
            round(b + (1.0 - b) * 0.45, 5),
            a,
        )
    r, g, b, a = rgba
    return (round(r * factor, 5), round(g * factor, 5), round(b * factor, 5), a)


# ----------------------------------------------------------------------
# template selection
# ----------------------------------------------------------------------
def score_template(template: GarmentTemplate, parsed: ParsedPrompt, text: str) -> float:
    score = 0.0
    if parsed.category and template.category == parsed.category:
        score += 10.0
    if parsed.silhouette and template.silhouette == parsed.silhouette:
        score += 4.0
    if parsed.hem and template.hem == parsed.hem:
        score += 2.0
    if parsed.sleeve and template.sleeve == parsed.sleeve:
        score += 1.5
    for tag in template.tags:
        if re.search(rf"(?<!\w){re.escape(tag.lower())}(?!\w)", text):
            score += 1.0
    if parsed.formality and parsed.formality in template.tags:
        score += 1.5
    return score


def select_template(catalog: TemplateCatalog, parsed: ParsedPrompt, text: str) -> GarmentTemplate:
    candidates = catalog.by_category(parsed.category) if parsed.category else catalog.all()
    if not candidates:
        candidates = catalog.all()
    if not candidates:
        raise PlanningError("no garment templates are installed")

    ranked = sorted(candidates, key=lambda t: (score_template(t, parsed, text), t.id), reverse=True)
    return ranked[0]


def display_name(prompt: str, parsed: ParsedPrompt) -> str:
    """A short, human-friendly look name, e.g. 'Burgundy Evening'."""
    parts: list[str] = []
    if parsed.color_name:
        parts.append(parsed.color_name.title())
    if parsed.formality == "formal":
        parts.append("Evening")
    elif parsed.formality == "casual":
        parts.append("Casual")
    elif parsed.formality == "sporty":
        parts.append("Sport")
    if parsed.category and len(parts) < 2:
        parts.append(parsed.category.title())

    if not parts:
        words = [w for w in re.split(r"\W+", prompt) if w][:3]
        parts = [w.title() for w in words] or ["Generated Look"]
    return " ".join(dict.fromkeys(parts))[:60]


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------
def plan_outfit(request: OutfitRequest, catalog: TemplateCatalog) -> OutfitPlan:
    """Resolve a prompt (plus any explicit overrides) into an outfit plan."""
    text = request.prompt.lower().strip()
    parsed = parse_prompt(request.prompt)

    # Explicit request fields always win over parsed ones.
    if request.category:
        parsed.category = request.category
    if request.silhouette:
        parsed.silhouette = request.silhouette
    if request.hem:
        parsed.hem = request.hem
    if request.color:
        parsed.color_name = request.color
        parsed.color_hex = COLORS.get(request.color.lower(), request.color)

    if request.template_id:
        template = catalog.get(request.template_id)
        if template is None:
            raise PlanningError(f"unknown template: {request.template_id!r}")
    else:
        if parsed.category is None:
            parsed.category = "dress"  # the most common ask; recorded as a note
        template = select_template(catalog, parsed, text)

    # Colour
    if parsed.color_hex:
        try:
            base_color = _shade(hex_to_linear_rgba(parsed.color_hex), text)
        except ValueError:
            base_color = (0.5, 0.5, 0.5, 1.0)
    else:
        base_color = hex_to_linear_rgba("#6b6f76")

    roughness, metallic = FABRICS.get(parsed.fabric or "", (0.7, 0.0))
    if not template.materials.supports_metallic:
        metallic = 0.0

    material = MaterialPlan(
        baseColor=base_color,
        colorName=parsed.color_name,
        metallic=metallic,
        roughness=roughness,
        fabric=parsed.fabric,
    )

    notes: list[str] = []
    if request.category is None and parsed.matched and not any(
        m in sum(CATEGORY_KEYWORDS.values(), ()) for m in parsed.matched
    ):
        notes.append("no garment category found in the prompt; defaulted to 'dress'")
    if parsed.color_name is None:
        notes.append("no colour found in the prompt; used a neutral grey")

    # Confidence: how many of the five styling axes the prompt actually pinned.
    resolved = sum(
        1 for value in (parsed.category, parsed.color_name, parsed.fabric, parsed.silhouette, parsed.hem)
        if value
    )

    return OutfitPlan(
        name=display_name(request.prompt, parsed),
        category=template.category,
        templateId=template.id,
        silhouette=parsed.silhouette or template.silhouette,
        hem=parsed.hem or template.hem,
        sleeve=parsed.sleeve or template.sleeve,
        material=material,
        keywords=sorted(set(parsed.matched)),
        confidence=round(resolved / 5.0, 2),
        notes=notes,
    )


def plan_with_llm(request: OutfitRequest, catalog: TemplateCatalog, completer=None) -> OutfitPlan:
    """Rule-based plan, optionally enriched by an LLM for unresolved fields.

    ``completer`` is any callable taking the prompt and returning a dict with
    optional ``category`` / ``silhouette`` / ``hem`` / ``color`` / ``fabric``
    keys. It is never allowed to override what the rules already resolved.
    """
    plan = plan_outfit(request, catalog)
    if completer is None or plan.confidence >= 0.8:
        return plan

    try:
        suggestion = completer(request.prompt) or {}
    except Exception:  # pragma: no cover - a styling hint is never load-bearing
        return plan

    enriched = request.model_copy(
        update={
            "category": request.category or suggestion.get("category"),
            "silhouette": request.silhouette or suggestion.get("silhouette"),
            "hem": request.hem or suggestion.get("hem"),
            "color": request.color or suggestion.get("color"),
        }
    )
    revised = plan_outfit(enriched, catalog)
    revised.notes.append("styling completed with LLM assistance")
    return revised


__all__ = [
    "COLORS",
    "FABRICS",
    "CATEGORY_KEYWORDS",
    "SILHOUETTE_KEYWORDS",
    "HEM_KEYWORDS",
    "SLEEVE_KEYWORDS",
    "ParsedPrompt",
    "parse_prompt",
    "plan_outfit",
    "plan_with_llm",
    "select_template",
    "display_name",
    "hex_to_linear_rgba",
    "srgb_to_linear",
]
