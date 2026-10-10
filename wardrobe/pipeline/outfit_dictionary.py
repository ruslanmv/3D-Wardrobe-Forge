"""OD1. The outfit dictionary: named sets of clothes this Forge can make, and who may wear them.

A client that lets a person (or a companion AI) ask for a look has the same problem twice:
it does not know what Forge can make, and it does not know which of those things need an
adult declaration. Guessing either is how a chat promises "a leather jacket with a hood"
that the planner turns into ``no_garment_template_matched``, or how a lingerie set ends up
listed among the casual looks. Both answers are Forge's, so the dictionary is Forge's.

Each entry is shorthand a person could have typed — a title, a group and a prompt in the
planner's own vocabulary — and grants nothing: a job for it is planned, fitted and gated
exactly as if the prompt had been written out. What the client needs to *decide* with is
computed from Forge's own planner, never written by hand:

- ``garments`` and ``slots`` — what the planner builds for the prompt;
- ``rating`` — ``private`` when any garment needs an adult declaration (an intimate
  category, a template that says so, or fabric the body shows through: the same
  ``requires_adult`` the job's gate reads), else ``general``.

So an entry cannot be mislabelled. A group's ``private`` flag is a *claim* about its
entries that ``tests/unit/test_outfit_dictionary.py`` checks against the computed rating
in both directions: a general group holding a see-through blouse fails, and so does a
lingerie group holding something the gate would let anyone wear.

The prompts reuse what already ships and is tested — the shipped pack's recipes, the look
and hosiery presets, the gallery's prompts — so the dictionary advertises looks the
pipeline is known to finish, not ones it might.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from wardrobe.domain.garments import INTIMATE_CATEGORIES, TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.pipeline.look_presets import LOOK_PRESETS

#: Where a garment of each category sits on her: what a "change the top" replaces.
SLOT_OF_CATEGORY: dict[str, str] = {
    "top": "top",
    "trousers": "bottom",
    "shorts": "bottom",
    "skirt": "bottom",
    "dress": "dress",
    "jumpsuit": "dress",
    "nightwear": "sleep",
    "jacket": "outer",
    "legwear": "legwear",
    "shoes": "shoes",
    "swimwear": "swim",
    "underwear": "underwear",
}


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    #: A claim about every entry in the group, checked against the computed rating.
    private: bool = False


GROUPS: tuple[Group, ...] = (
    Group("casual", "Casual"),
    Group("dressy", "Dressy"),
    # DC3. Sexy Discoteca — All Black: the bodycon dress with each of four black boots.
    Group("discoteca", "Sexy Discoteca · All Black"),
    Group("smart", "Smart"),
    Group("cozy", "Cozy & home"),
    Group("summer", "Summer"),
    Group("swim", "Swimwear", private=True),
    Group("lingerie", "Lingerie", private=True),
    Group("legwear", "Stockings & legwear", private=True),
    Group("sheer", "Sheer", private=True),
)


@dataclass(frozen=True)
class Outfit:
    id: str
    title: str
    group: str
    prompt: str
    #: A look or hosiery preset whose blocks (visible thong, suspenders) the prompt needs.
    preset: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def request(self) -> OutfitRequest:
        fields: dict = {"prompt": self.prompt}
        if self.preset:
            fields["preset"] = self.preset
        return OutfitRequest.model_validate(fields)


OUTFITS: tuple[Outfit, ...] = (
    # --- casual ---------------------------------------------------------
    Outfit(
        "crop-top-jeans",
        "Crop top & jeans",
        "casual",
        "black fitted crop top + blue straight jeans",
        tags=("denim", "day"),
    ),
    Outfit(
        "tee-jeans", "Tee & jeans", "casual", "white fitted tee + blue straight jeans", tags=("denim", "day")
    ),
    Outfit(
        "denim-shorts",
        "Denim shorts",
        "casual",
        "white cropped tee + blue denim shorts",
        tags=("denim", "summer"),
    ),
    Outfit(
        "tube-top-baggy-jeans",
        "Tube top & baggy jeans",
        "casual",
        "white tube top + blue baggy jeans",
        tags=("denim", "y2k"),
    ),
    Outfit(
        "cami-wide-leg",
        "Cami & wide-leg trousers",
        "casual",
        "black cropped cami + cream wide-leg trousers",
        tags=("day",),
    ),
    Outfit(
        "halter-skater",
        "Halter top & skater skirt",
        "casual",
        "red halter crop top + black skater skirt",
        tags=("party",),
    ),
    Outfit(
        "leggings-cardigan",
        "Leggings & cropped cardigan",
        "casual",
        "white fitted tee + cream cropped cardigan + black leggings",
        tags=("comfy",),
    ),
    # --- dressy ---------------------------------------------------------
    Outfit(
        "little-black-dress", "Little black dress", "dressy", "black satin cocktail dress", tags=("evening",)
    ),
    Outfit("red-bodycon", "Red bodycon mini", "dressy", "red bodycon mini dress", tags=("party", "evening")),
    Outfit(
        "evening-gown",
        "Evening gown",
        "dressy",
        "black satin evening column gown",
        tags=("evening", "formal"),
    ),
    Outfit("wrap-dress", "Wrap dress", "dressy", "red long-sleeved wrap dress", tags=("evening",)),
    Outfit("slip-dress", "Satin slip dress", "dressy", "champagne satin slip dress", tags=("evening",)),
    Outfit("skater-dress", "Skater dress", "dressy", "navy skater mini dress", tags=("party",)),
    Outfit(
        "corset-mini",
        "Corset top & mini",
        "dressy",
        "black corset top + black low-rise pleated mini skirt",
        preset="corset_top_low_rise_mini",
        tags=("party",),
    ),
    # --- discoteca (wardrobe.pipeline.fashion_collections) ---------------
    Outfit("discoteca-stiletto-ankle", "Black dress & stiletto ankle boots", "discoteca",
           LOOK_PRESETS["discoteca_stiletto_ankle"]["prompt"], tags=("party", "night", "boots")),
    Outfit("discoteca-platform", "Black dress & platform boots", "discoteca",
           LOOK_PRESETS["discoteca_platform"]["prompt"], tags=("party", "night", "boots")),
    Outfit("discoteca-combat", "Black dress & combat boots", "discoteca",
           LOOK_PRESETS["discoteca_combat"]["prompt"], tags=("party", "night", "boots")),
    Outfit("discoteca-over-knee", "Black dress & over-the-knee boots", "discoteca",
           LOOK_PRESETS["discoteca_over_knee"]["prompt"], tags=("party", "night", "boots")),
    # --- smart ----------------------------------------------------------
    Outfit(
        "blazer-trousers",
        "Blazer & trousers",
        "smart",
        "black blazer + white blouse + black straight trousers",
        tags=("work",),
    ),
    Outfit(
        "blouse-pencil", "Blouse & pencil skirt", "smart", "white blouse + black pencil skirt", tags=("work",)
    ),
    Outfit("shirt-dress", "Shirt dress", "smart", "light blue shirt dress", tags=("work", "day")),
    Outfit(
        "trench-jeans",
        "Trench & slim jeans",
        "smart",
        "beige lightweight trench + white fitted tee + blue slim jeans",
        tags=("day",),
    ),
    # --- cozy & home ----------------------------------------------------
    Outfit(
        "cardigan-trousers",
        "Cardigan & trousers",
        "cozy",
        "grey long cardigan + white fitted tee + black straight trousers",
        tags=("comfy",),
    ),
    # "bottoms", not "trousers": the word "trousers" is a category keyword and wins over the
    # nightwear template's own tags, which would put her in office trousers to sleep.
    Outfit("pajamas", "Pajamas", "cozy", "pink pajama shirt + pink pajama bottoms", tags=("sleep", "comfy")),
    Outfit("nightgown", "Satin nightgown", "cozy", "champagne satin nightgown", tags=("sleep",)),
    # --- summer ---------------------------------------------------------
    Outfit("yellow-sundress", "Yellow sundress", "summer", "yellow maxi sundress", tags=("day",)),
    Outfit(
        "maxi-skirt",
        "Tee & tiered maxi skirt",
        "summer",
        "white fitted tee + blue tiered maxi skirt",
        tags=("day",),
    ),
    Outfit("a-line-dress", "A-line dress", "summer", "light blue a-line dress", tags=("day",)),
    Outfit(
        "linen-shorts", "Blouse & linen shorts", "summer", "white blouse + beige linen shorts", tags=("day",)
    ),
    # --- swimwear (private) ---------------------------------------------
    Outfit("triangle-bikini", "Triangle bikini", "swim", "red triangle bikini", tags=("beach",)),
    Outfit("bandeau-bikini", "Bandeau bikini", "swim", "white bandeau bikini", tags=("beach",)),
    Outfit("one-piece", "One-piece swimsuit", "swim", "black one-piece swimsuit", tags=("beach",)),
    Outfit("skirted-swimsuit", "Skirted swimsuit", "swim", "navy skirted swimsuit", tags=("beach",)),
    # --- lingerie (private) ---------------------------------------------
    Outfit("lace-lingerie-set", "Lace lingerie set", "lingerie", "black lace lingerie set"),
    Outfit("balconette-set", "Balconette bra & briefs", "lingerie", "red balconette bra + red briefs"),
    Outfit("plunge-thong", "Plunge bra & thong", "lingerie", "white plunge bra + white thong"),
    Outfit("bodysuit", "Lace bodysuit", "lingerie", "black lace bodysuit"),
    Outfit("guepiere", "Guêpière", "lingerie", "black guêpière"),
    Outfit(
        "visible-thong-jeans",
        "Visible thong & low-rise jeans",
        "lingerie",
        "white fitted crop top + blue low-rise straight jeans + black tailored v-string",
        preset="visible_thong_low_rise_jeans",
        tags=("y2k",),
    ),
    # LC5. The Italian lace collection (wardrobe.lingerie.collections): one bralette, two bottoms.
    Outfit(
        "italian-lace-thong",
        "Italian lace set · thong",
        "lingerie",
        "black tailored triangle bralette + black tailored thong",
        preset="italian_lace_thong_set",
        tags=("collection",),
    ),
    Outfit(
        "italian-lace-brazilian",
        "Italian lace set · Brazilian",
        "lingerie",
        "black tailored triangle bralette + black tailored brazilian briefs",
        preset="italian_lace_brazilian_set",
        tags=("collection",),
    ),
    # --- stockings & legwear (private) ----------------------------------
    # The hosiery presets (wardrobe.hosiery.presets) carry what a prompt cannot say: the
    # suspender belt, its straps, the denier and how much the hem reveals. Sent with the
    # outfit's own prompt, a preset fills those blocks and keeps the prompt.
    Outfit(
        "stockings-mini-dress",
        "Mini dress & stockings",
        "legwear",
        "black bodycon mini dress",
        preset="classic_black_mini_dress",
        tags=("evening",),
    ),
    Outfit(
        "stockings-pencil",
        "Pencil skirt & seamed stockings",
        "legwear",
        "black pencil skirt + white fitted blouse",
        preset="vintage_seamed",
        tags=("evening", "vintage"),
    ),
    Outfit(
        "stockings-discreet",
        "Knee-length skirt & stockings",
        "legwear",
        "black knee-length pencil skirt + white fitted blouse",
        preset="discreet_black",
        tags=("work",),
    ),
    Outfit(
        "fishnets-mini",
        "Mini skirt & fishnets",
        "legwear",
        "black mini skirt + black fitted top",
        preset="fishnet_black",
        tags=("party",),
    ),
    # --- sheer (private) ------------------------------------------------
    Outfit("sheer-blouse", "Sheer blouse & mini", "sheer", "sheer white blouse + black mini skirt"),
)


def groups() -> dict[str, Group]:
    return {group.id: group for group in GROUPS}


def plan_entry(outfit: Outfit, catalog: TemplateCatalog) -> dict:
    """The entry with what Forge's planner makes of it: garments, slots and rating."""
    from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

    plan = plan_outfit_stack(outfit.request(), catalog)
    garments = []
    for garment in plan.garments:
        gated = garment.category in INTIMATE_CATEGORIES or bool(garment.requires_adult)
        garments.append(
            {
                "name": garment.name,
                "category": garment.category,
                "template": garment.template_id,
                "slot": SLOT_OF_CATEGORY.get(garment.category, garment.category),
                "adultGate": gated,
            }
        )
    private = any(g["adultGate"] for g in garments)
    return {
        "id": outfit.id,
        "title": outfit.title,
        "group": outfit.group,
        "prompt": outfit.prompt,
        **({"preset": outfit.preset} if outfit.preset else {}),
        # Exactly the `outfit` body a job for this entry sends: the prompt, and the preset
        # whose blocks the prompt cannot express.
        "request": outfit.request().model_dump(by_alias=True, exclude_none=True, exclude_defaults=True),
        "tags": list(outfit.tags),
        "rating": "private" if private else "general",
        "slots": list(dict.fromkeys(g["slot"] for g in garments)),
        "garments": garments,
    }


@lru_cache(maxsize=4)
def _catalogue(catalog_id: int, catalog: TemplateCatalog) -> tuple[dict, ...]:
    return tuple(plan_entry(outfit, catalog) for outfit in OUTFITS)


def catalogue(catalog: TemplateCatalog) -> dict:
    """``GET /v1/outfits``: the groups and every entry, planned. Cached per catalogue."""
    entries = [dict(entry) for entry in _catalogue(id(catalog), catalog)]
    return {
        "version": 1,
        "groups": [{"id": g.id, "title": g.title, "private": g.private} for g in GROUPS],
        "outfits": entries,
    }


__all__ = ["GROUPS", "OUTFITS", "SLOT_OF_CATEGORY", "Group", "Outfit", "catalogue", "groups", "plan_entry"]
