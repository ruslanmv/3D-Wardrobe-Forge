"""Finishes, see-through fabrics and patterns: the vocabulary, and what each one means.

A garment's look used to be a colour plus two PBR numbers, roughness and
metallic. That was never enough, and on the avatars this project dresses it
was less than it seemed: VRoid models are cel-shaded MToon, and a garment
borrows the avatar's MToon so it shades like her own clothes. MToon has no
roughness and no metalness. "Latex" planned roughness 0.15 and rendered as
flat colour, like everything else.

So a finish here is described in the terms a toon shader *does* have: a
parametric rim (a Fresnel edge light) and a matcap (an additive highlight
looked up by the surface's view-space normal). Gloss is a sharp matcap spot
and a bright thin rim; satin a broad soft one; metallic an environment band
tinted by the colour; sequins a sparkle matcap over a sequin texture. Roughness
and metallic are still carried, for an avatar with no MToon to borrow, where
the garment falls back to glTF PBR and they mean what they say.

Opacity and patterns are the other half. Lace and fishnet are *holes*: an
alpha-masked texture, not geometry. Sheer fabric is alpha blending. Stripes,
dots and gingham are colour baked into a tiling texture.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finish:
    name: str
    #: For the PBR fallback (a model without MToon).
    roughness: float
    metallic: float
    #: Parametric rim: brightness 0..1, Fresnel power (higher = thinner), lift.
    rim: float = 0.0
    rim_power: float = 5.0
    rim_lift: float = 0.0
    #: Matcap highlight style (see ``textures.matcap``) and its strength, 0..1.
    matcap: str | None = None
    matcap_strength: float = 0.0
    #: The matcap takes the garment's colour (metal) rather than staying white (gloss).
    tinted: bool = False
    #: Shade colour as a fraction of the lit colour. Lower is more contrast: shine
    #: reads against a deep shadow, which is how cel art draws latex and metal.
    shade: float = 0.72


FINISHES: dict[str, Finish] = {
    "matte": Finish("matte", roughness=0.85, metallic=0.0),
    "satin": Finish("satin", roughness=0.3, metallic=0.0, rim=0.22, rim_power=3.0, matcap="satin",
                    matcap_strength=0.32),
    "gloss": Finish("gloss", roughness=0.15, metallic=0.0, rim=0.3, rim_power=4.0, matcap="gloss",
                    matcap_strength=0.6, shade=0.58),
    "latex": Finish("latex", roughness=0.06, metallic=0.0, rim=0.42, rim_power=5.0, matcap="latex",
                    matcap_strength=0.9, shade=0.45),
    "metallic": Finish("metallic", roughness=0.2, metallic=0.85, rim=0.35, rim_power=3.0, matcap="metal",
                       matcap_strength=0.75, tinted=True, shade=0.42),
    "sequin": Finish("sequin", roughness=0.2, metallic=0.6, rim=0.3, rim_power=3.0, matcap="sparkle",
                     matcap_strength=0.8, tinted=True, shade=0.5),
}

#: Longest phrase wins, as everywhere in the planner. A word sits in one list only.
FINISH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "matte": ("matte", "matt"),
    "satin": ("satin", "silk", "silky", "sateen", "charmeuse"),
    "gloss": ("glossy", "gloss", "shiny", "wet look", "wet-look", "patent", "lacquered"),
    "latex": ("latex", "pvc", "vinyl", "rubber"),
    "metallic": ("metallic", "chrome", "foil", "lame", "lamé", "liquid metal", "holographic"),
    "sequin": ("sequin", "sequins", "sequined", "sequinned", "glitter", "sparkly", "sparkle", "rhinestone"),
}

#: A shiny garment in a metal's colour is a metallic one: "shiny silver mini dress".
METAL_COLOURS = frozenset({"silver", "gold", "bronze", "copper", "rose gold", "champagne"})

#: Words that make a fabric see-through, and how opaque it stays (0..1).
OPACITY_KEYWORDS: dict[float, tuple[str, ...]] = {
    0.3: ("transparent", "see-through", "see through"),
    0.45: ("sheer", "mesh", "tulle", "organza", "voile"),
    0.65: ("semi-sheer", "semi sheer", "semi-transparent", "translucent"),
}

#: Opacity names the Studio offers, highest first.
OPACITY_LEVELS: dict[str, float] = {"opaque": 1.0, "semi-sheer": 0.65, "sheer": 0.45, "transparent": 0.3}

#: Below this a garment never goes: fully clear fabric is not a garment.
MIN_OPACITY = 0.2


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    #: How the texture's alpha is used: "mask" makes holes (lace, fishnet).
    alpha: str = "opaque"
    #: Physical size of one tile of the texture, in metres.
    tile_m: float = 0.05
    #: The texture carries colour (stripes) rather than a grey the colour tints (lace).
    coloured: bool = False


PATTERNS: dict[str, Pattern] = {
    "none": Pattern("none"),
    "lace": Pattern("lace", alpha="mask", tile_m=0.07),
    "fishnet": Pattern("fishnet", alpha="mask", tile_m=0.014),
    "sequin": Pattern("sequin", tile_m=0.03),
    "stripes": Pattern("stripes", tile_m=0.05, coloured=True),
    "dots": Pattern("dots", tile_m=0.04, coloured=True),
    "gingham": Pattern("gingham", tile_m=0.03, coloured=True),
    "plaid": Pattern("plaid", tile_m=0.09, coloured=True),
}

PATTERN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "lace": ("lace", "lacy", "embroidered lace", "eyelash lace"),
    "fishnet": ("fishnet", "fishnets", "fish-net", "fishnet stockings"),
    "stripes": ("striped", "stripes", "stripe", "pinstripe", "pinstriped", "breton"),
    "dots": ("polka dot", "polka dots", "polka-dot", "dotted", "spotted"),
    "gingham": ("gingham", "checked", "checkered"),
    "plaid": ("plaid", "tartan"),
}


def resolve_alpha_mode(pattern: str, opacity: float) -> str:
    """How the renderer treats the garment's alpha: opaque, mask (holes) or blend."""
    if opacity < 0.999:
        return "blend"
    return PATTERNS.get(pattern, PATTERNS["none"]).alpha


def texture_scale(pattern: str) -> float:
    """Tiles per metre for a pattern; 0 when there is no texture."""
    spec = PATTERNS.get(pattern)
    return 0.0 if spec is None or spec.name == "none" else round(1.0 / spec.tile_m, 3)


__all__ = [
    "FINISHES",
    "FINISH_KEYWORDS",
    "Finish",
    "METAL_COLOURS",
    "MIN_OPACITY",
    "OPACITY_KEYWORDS",
    "OPACITY_LEVELS",
    "PATTERNS",
    "PATTERN_KEYWORDS",
    "Pattern",
    "resolve_alpha_mode",
    "texture_scale",
]
