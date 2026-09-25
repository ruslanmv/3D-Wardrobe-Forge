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

from wardrobe.domain.garments import (
    COVERAGE_PRESETS,
    INTIMATE_CATEGORIES,
    STRAP_PRESETS,
    GarmentTemplate,
    TemplateCatalog,
)
from wardrobe.domain.looks import MaterialPlan, OutfitPlan, OutfitRequest, StylePlan
from wardrobe.errors import PlanningError
from wardrobe.materials.finishes import (
    FINISH_KEYWORDS,
    FINISHES,
    METAL_COLOURS,
    MIN_OPACITY,
    OPACITY_KEYWORDS,
    PATTERN_KEYWORDS,
    PATTERNS,
    resolve_alpha_mode,
    texture_scale,
)

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
    "neon pink": "#ff2fa0",
    "champagne": "#e6d2ae",
    "nude": "#d9b39a",
    "neon green": "#39ff14",
    "neon yellow": "#e8ff1a",
    "neon orange": "#ff6a13",
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
    "skirt": ("skirt", "gonna", "minigonna"),
    "jacket": ("jacket", "blazer", "coat", "parka", "cardigan", "trench"),
    "trousers": ("trousers", "pants", "jeans", "slacks", "chinos", "leggings"),
    "top": (
        "top", "shirt", "blouse", "tee", "t-shirt", "sweater", "hoodie", "jumper", "crop top", "tube top",
        "halter top", "cami", "crop cami", "cami top", "tank top",
    ),
    "shoes": ("shoes", "boots", "heels", "sneakers", "trainers", "sandals"),
    # try-on haul. The planner takes the longest phrase that matches, so a word
    # must never sit in two categories: "bandeau" is a template tag, not a
    # keyword, or "bandeau bikini" would plan a top.
    "shorts": ("shorts", "hot pants", "cut-offs"),
    "swimwear": (
        "swimwear", "swimsuit", "bikini", "monokini", "bathing suit", "tankini", "swim dress",
        "one-piece swimsuit",
    ),
    "underwear": (
        "underwear", "lingerie", "bra", "bralette", "panties", "briefs", "knickers", "bodysuit", "teddy",
        "garter belt", "suspender belt", "garter", "garters", "garter set",
    ),
    "jumpsuit": ("jumpsuit", "catsuit", "unitard", "boilersuit"),
    "nightwear": (
        "nightwear", "nightgown", "nightdress", "nightie", "chemise", "pajamas", "pyjamas", "pajama",
        "pyjama", "sleepwear",
    ),
    "legwear": (
        "stockings", "thigh highs", "thigh-highs", "thigh-high socks", "over-the-knee socks",
        "tights", "pantyhose", "hosiery", "hose",
        # Italian, as designers write it
        "calze", "calze a rete", "collant", "collant a rete", "autoreggenti",
    ),
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
    "mini": ("mini", "short", "above the knee", "minigonna"),
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


#: Colour words in other languages designers write in, and the colour each one is.
COLOR_ALIASES: dict[str, str] = {
    **dict.fromkeys(("nero", "nera", "neri", "nere"), "black"),
    **dict.fromkeys(("bianco", "bianca", "bianchi", "bianche"), "white"),
    **dict.fromkeys(("rosso", "rossa", "rossi", "rosse"), "red"),
    **dict.fromkeys(("rosa",), "pink"),
    **dict.fromkeys(("blu",), "navy"),
}

#: What a fabric word implies about its finish when no finish word is given.
FABRIC_FINISH: dict[str, str] = {
    "satin": "satin",
    "silk": "satin",
    "leather": "satin",
    "sequin": "sequin",
    "sequined": "sequin",
    "metallic": "metallic",
    "latex": "latex",
}

#: How much of the body a garment covers. "micro" is a coverage, not a category:
#: a micro bikini is a bikini, a micro mini is a mini skirt, cut smaller.
COVERAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "micro": ("micro", "micro-mini", "micro mini", "thong", "g-string", "tiny"),
    "minimal": ("minimal", "skimpy", "cheeky", "brazilian", "barely-there", "barely there"),
    "full": ("full coverage", "full-coverage", "modest"),
}

STRAP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "string": ("string", "tie-side", "side-tie", "tie side", "side tie", "string bikini"),
    "halter": ("halter", "halterneck", "halter-neck"),
    "none": ("strapless", "bandeau"),
    "cross-back": ("cross-back", "crossback", "criss-cross", "criss cross", "crisscross"),
    "garter": ("garter", "garters", "suspender", "suspenders", "garter belt"),
    "harness": ("harness", "strappy", "caged"),
    "shoulder": ("spaghetti strap", "spaghetti straps", "spaghetti-strap"),
}

NECKLINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "v": ("v-neck", "v neck", "v-neckline", "vneck"),
    "plunge": ("plunge", "plunging", "deep v", "deep-v"),
    "sweetheart": ("sweetheart",),
    "triangle": ("triangle",),
    "demi": ("demi", "demi-cup", "demi cup", "half-cup", "half cup"),
    "balconette": ("balconette", "balcony", "balconnet"),
}

RISE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "high": ("high-waisted", "high waisted", "high-rise", "high rise", "high-waist"),
    "low": ("low-rise", "low rise", "hipster", "low-slung"),
}

BACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "low": ("backless", "open back", "open-back", "low back", "low-back"),
}

LEG_CUT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "high": ("high-cut", "high cut", "high-leg", "high leg", "french cut", "french-cut"),
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
    finish: str | None = None
    opacity: float | None = None
    pattern: str | None = None
    pattern_color_hex: str | None = None
    coverage: str | None = None
    straps: str | None = None
    neckline: str | None = None
    back: str | None = None
    leg_cut: str | None = None
    rise: str | None = None
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

    for attribute, table in (
        ("finish", FINISH_KEYWORDS),
        ("pattern", PATTERN_KEYWORDS),
        ("coverage", COVERAGE_KEYWORDS),
        ("straps", STRAP_KEYWORDS),
        ("neckline", NECKLINE_KEYWORDS),
        ("back", BACK_KEYWORDS),
        ("leg_cut", LEG_CUT_KEYWORDS),
        ("rise", RISE_KEYWORDS),
    ):
        value, matched = _find(text, table)
        setattr(parsed, attribute, value)
        parsed.matched.extend(matched)

    opacity, matched = _find(text, {str(level): words for level, words in OPACITY_KEYWORDS.items()})
    if opacity is not None:
        parsed.opacity = float(opacity)
        parsed.matched.extend(matched)

    # Colour: take the earliest mention, and the longest name at that position.
    # 'navy blue' is navy; 'blue denim jacket' is blue. A second, different colour
    # is the pattern's: "red and white striped" is red with white stripes.
    matches: list[tuple[int, int, str]] = []
    for name in [*COLORS, *COLOR_ALIASES]:
        for found in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text):
            matches.append((found.start(), -len(name), COLOR_ALIASES.get(name, name)))
    matches.sort()
    chosen: list[tuple[int, int, str]] = []
    for start, negative_length, name in matches:
        # A name inside one already taken is part of it, and so is one right after
        # it: "navy blue" and "sky-blue" are one colour, not a navy with blue stripes.
        if any(s0 <= start < s0 - n0 for s0, n0, _ in chosen):
            continue
        if chosen and not text[chosen[-1][0] - chosen[-1][1] : start].strip(" -"):
            continue
        if not chosen or COLORS[name] != COLORS[chosen[-1][2]]:
            chosen.append((start, negative_length, name))
    if chosen:
        name = chosen[0][2]
        parsed.color_name = name
        parsed.color_hex = COLORS[name]
        parsed.matched.append(name)
    if len(chosen) > 1:
        parsed.pattern_color_hex = COLORS[chosen[1][2]]
        parsed.matched.append(chosen[1][2])
    if parsed.finish == "gloss" and parsed.color_name in METAL_COLOURS:
        parsed.finish = "metallic"  # "shiny silver" is metal, not lacquer

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
    # A garment named outright beats one that only shares a word with the prompt:
    # "lace bodysuit" is the Bodysuit, not the Lingerie Set tagged "lace". Ties
    # used to fall to the template id's alphabetical order.
    name = template.name.lower()
    if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) or re.search(
        rf"(?<!\w){re.escape(name.split()[-1])}(?!\w)", text
    ):
        score += 1.5
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


def display_name(prompt: str, parsed: ParsedPrompt, template: GarmentTemplate | None = None) -> str:
    """A short, human-friendly look name, e.g. 'Burgundy Evening' or 'Red Triangle Bikini'.

    Where the name would otherwise end in the bare category, the template's own
    name is used. In a haul every look is announced by name, and "Red Swimwear",
    "Black Underwear", "Nightwear" said nothing about which of four swimsuits or
    three lingerie pieces was on screen.
    """
    parts: list[str] = []
    if parsed.color_name:
        parts.append(parsed.color_name.title())
    # The word that makes this look distinct from the last one in a haul: the
    # finish, the see-through fabric, the pattern, or the cut. Not counted
    # against the two-word budget, so the garment's own name still follows.
    descriptor = _descriptor(parsed)
    if parsed.formality == "formal":
        parts.append("Evening")
    elif parsed.formality == "casual":
        parts.append("Casual")
    elif parsed.formality == "sporty":
        parts.append("Sport")
    if parsed.category and len(parts) < 2:
        parts.append(template.name.title() if template is not None else parsed.category.title())

    if not parts:
        words = [w for w in re.split(r"\W+", prompt) if w][:3]
        parts = [w.title() for w in words] or ["Generated Look"]
    if descriptor and descriptor.lower() not in " ".join(parts).lower():
        parts.insert(1 if parsed.color_name else 0, descriptor)
    return " ".join(dict.fromkeys(parts))[:60]


def _descriptor(parsed: ParsedPrompt) -> str | None:
    if parsed.coverage == "micro":
        return "Micro"
    if parsed.opacity is not None:
        if parsed.opacity >= 0.65:
            return "Translucent"
        return "Sheer" if parsed.opacity >= 0.5 else "Transparent"
    if parsed.pattern and parsed.pattern != "none":
        return {"stripes": "Striped", "dots": "Polka Dot"}.get(parsed.pattern, parsed.pattern.title())
    return {"latex": "Latex", "metallic": "Metallic", "sequin": "Sequin", "gloss": "Glossy"}.get(
        parsed.finish or ""
    )


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

    adjustments: list[str] = []
    material = resolve_material(parsed, request, template, text, adjustments)
    style = resolve_style(parsed, request, template)
    requires_adult = (
        template.category in INTIMATE_CATEGORIES or template.requires_adult or material.exposes_body
    )

    notes: list[str] = list(adjustments)
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
        name=display_name(request.prompt, parsed, template),
        category=template.category,
        templateId=template.id,
        silhouette=parsed.silhouette or template.silhouette,
        hem=parsed.hem or template.hem,
        sleeve=parsed.sleeve or template.sleeve,
        material=material,
        style=style,
        requiresAdult=requires_adult,
        keywords=sorted(set(parsed.matched)),
        confidence=round(resolved / 5.0, 2),
        notes=notes,
    )


def _colour(hex_value: str | None, text: str, fallback: str) -> tuple[float, float, float, float]:
    try:
        return _shade(hex_to_linear_rgba(hex_value), text) if hex_value else hex_to_linear_rgba(fallback)
    except ValueError:
        return hex_to_linear_rgba(fallback)


def _luminance(rgba: tuple[float, ...]) -> float:
    return 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]


def resolve_material(
    parsed: ParsedPrompt,
    request: OutfitRequest,
    template: GarmentTemplate,
    text: str,
    notes: list[str] | None = None,
) -> MaterialPlan:
    """Colour, finish, see-through and pattern — each limited by what the template supports.

    ``notes`` collects what was adjusted (an opacity below the minimum, say), so the
    plan reports it instead of silently changing the request.
    """
    notes = notes if notes is not None else []
    base_color = _colour(parsed.color_hex, text, "#6b6f76")
    policy = template.materials

    finish = request.finish or parsed.finish or FABRIC_FINISH.get(parsed.fabric or "") or "matte"
    if finish not in FINISHES or not policy.supports_finish:
        finish = "matte"

    pattern = request.pattern or parsed.pattern or ("sequin" if finish == "sequin" else "none")
    if pattern not in PATTERNS or not policy.supports_pattern:
        pattern = "none"
    pattern_color = None
    if PATTERNS[pattern].coloured:
        # A second colour in the prompt; else white on a dark garment, black on a light one.
        fallback = "#f3f2ee" if _luminance(base_color) < 0.45 else "#15151a"
        pattern_color = _colour(parsed.pattern_color_hex, "", fallback)

    opacity = request.opacity if request.opacity is not None else (parsed.opacity or 1.0)
    if opacity < MIN_OPACITY:
        notes.append(f"opacity {opacity:g} is below the renderer's minimum; clamped to {MIN_OPACITY:g}")
        opacity = MIN_OPACITY
    # "Sheer lace" and "see-through fishnet" describe the holes, not a second
    # veil over them: a cut-out pattern at full opacity, its gaps open. Only an
    # explicit opacity value makes the threads themselves translucent too.
    if PATTERNS[pattern].alpha == "mask" and request.opacity is None and parsed.opacity is not None:
        opacity = 1.0
    if not policy.supports_transparency:
        if opacity < 1.0 or PATTERNS[pattern].alpha == "mask":
            notes.append(f"{template.name} cannot be see-through; rendered opaque")
        opacity = 1.0
    # Lining. Asked for, it is honoured: "lined lace" is lined, lingerie included.
    # Unasked, lace outside the intimate categories is lined (a lace top or dress
    # is), and lace lingerie is not; "sheer" or "unlined" always unlines it. That
    # keeps "lace crop cami" an everyday top rather than tripping the adult gate.
    unlined = bool(re.search(r"(?<!\w)unlined(?!\w)", text)) or parsed.opacity is not None
    asked_lined = bool(re.search(r"(?<!\w)lined(?!\w)", text)) and not unlined
    lined = pattern == "lace" and opacity >= 0.999 and not unlined and (
        asked_lined or template.category not in INTIMATE_CATEGORIES
    )
    if lined or not policy.supports_transparency:
        alpha_mode = "opaque"
    else:
        alpha_mode = resolve_alpha_mode(pattern, opacity)

    spec = FINISHES[finish]
    if parsed.fabric and finish == FABRIC_FINISH.get(parsed.fabric, "matte"):
        roughness, metallic = FABRICS.get(parsed.fabric, (spec.roughness, spec.metallic))
    elif finish != "matte":
        roughness, metallic = spec.roughness, spec.metallic
    else:
        roughness, metallic = FABRICS.get(parsed.fabric or "", (0.7, 0.0))
    if not policy.supports_metallic:
        metallic = 0.0

    return MaterialPlan(
        baseColor=base_color,
        colorName=parsed.color_name,
        metallic=metallic,
        roughness=roughness,
        fabric=parsed.fabric,
        finish=finish,
        opacity=round(opacity, 3),
        alphaMode=alpha_mode,
        pattern=pattern,
        patternColor=pattern_color,
        textureScale=texture_scale(pattern),
        lined=lined,
    )


def resolve_style(parsed: ParsedPrompt, request: OutfitRequest, template: GarmentTemplate) -> StylePlan:
    """Coverage, straps and cut: request, then prompt, then the template's own."""
    fit = template.fit
    coverage = request.coverage or parsed.coverage or fit.coverage
    straps = request.straps or parsed.straps or fit.straps
    neckline = request.neckline or parsed.neckline or fit.neckline
    return StylePlan(
        coverage=coverage if coverage in COVERAGE_PRESETS else "standard",
        straps=straps if straps in STRAP_PRESETS else fit.straps,
        neckline=neckline,
        back=parsed.back or fit.back,
        legCut=parsed.leg_cut or fit.leg_cut,
        rise=parsed.rise or "",
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
