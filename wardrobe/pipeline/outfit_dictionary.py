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
from wardrobe.pipeline.fashion_collections import outfit_prompt
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
    # DC3. Sexy Discoteca — All Black: the bodycon dress with each of four black boots. Shown to
    # everyone as a night-out set (the collection keeps its own name).
    Group("discoteca", "Night out · All black"),
    Group("smart", "Smart"),
    # OC1. Training, yoga and athleisure: what the Gym occasion (wardrobe.pipeline.occasions) offers.
    Group("active", "Active & gym"),
    Group("cozy", "Cozy & home"),
    Group("summer", "Summer"),
    Group("swim", "Swimwear", private=True),
    Group("lingerie", "Lingerie", private=True),
    Group("legwear", "Stockings & legwear", private=True),
    Group("sheer", "Sheer", private=True),
    # AB. An independent collection's own group (wardrobe.collections): swimwear, so private.
    Group("anime-beachwear", "Anime Beachwear", private=True),
    # AN2. One collection, two groups: a group's private flag must match what Forge computes.
    # Named for what the looks are, anime-inspired outfits, on a screen anyone may see.
    Group("anime", "Anime-inspired"),
    Group("anime-private", "Anime-inspired · swim & bodysuits", private=True),
    # RP1. Classic adult role-play costumes, made of catalogue garments only: no hat, badge,
    # apron or stethoscope is claimed, because Forge builds none. Each wears sheer stockings,
    # so each is gated as the stockings are, and the group says so.
    Group("roleplay", "Role-play · adults", private=True),
    # AA. Cards the atelier added. Private because every look in it is gated
    # (see-through, or a bra worn as a top). General new cards stay in their own groups.
    Group("atelier", "Atelier · adults", private=True),
    # ES3. Erotic sets for private scenes, each dressed over her prepared bare body (base
    # "bare-dressed"), so whatever comes off — the whole set, or only its top or only its bottom
    # (the visibility answer by slot, ES2) — shows her own skin and its detail, not painted clothing.
    Group("erotic", "Erotic sets · adults", private=True),
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
    #: AB. (collection, design id): a design of an independent collection (wardrobe.collections).
    design: tuple[str, str] | None = None
    #: ES3. The base body the set is built on: "bare-dressed" for the erotic sets. None — every other
    #: entry — dresses her as she is.
    base: str | None = None

    def request(self) -> OutfitRequest:
        fields: dict = {"prompt": self.prompt}
        if self.preset:
            fields["preset"] = self.preset
        if self.design:
            fields["design"] = {"collection": self.design[0], "id": self.design[1]}
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
    # CR1. The Y2K low rise: a cropped cami over low-rise baggy jeans, her waist bare above the
    # waistband front and back (measured: waistline and lower back 100% bare on the fit form).
    Outfit(
        "y2k-low-rise",
        "Y2K low rise",
        "casual",
        "white cropped cami + blue low-rise baggy jeans",
        tags=("y2k", "denim", "waistline"),
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
    # OC1. The rest of the casual looks the occasions (wardrobe.pipeline.occasions) offer for
    # shopping and campus: streetwear, a cute set, and two quieter ones. Each prompt was planned
    # before it was written here, and test_every_entry_plans_to_real_templates keeps it so.
    Outfit(
        "street-coat-baggy",
        "Coat, baggy jeans & combat boots",
        "casual",
        "black oversized coat + white cropped tee + blue baggy jeans + black combat boots",
        tags=("streetwear",),
    ),
    Outfit(
        "cami-balloon",
        "Cami & balloon trousers",
        "casual",
        "white cropped cami + khaki balloon trousers",
        tags=("streetwear",),
    ),
    Outfit(
        "pleated-cardigan",
        "Tee, cardigan & pleated mini",
        "casual",
        "white fitted tee + pink cropped cardigan + pink pleated mini skirt",
        tags=("cute",),
    ),
    Outfit(
        "cardigan-jeans",
        "Long cardigan & jeans",
        "casual",
        "grey long cardigan + white fitted tee + blue straight jeans",
        tags=("comfy", "day"),
    ),
    Outfit(
        "tee-trousers-flats",
        "Tee, trousers & flats",
        "casual",
        "white fitted tee + navy straight trousers + white flat shoes",
        tags=("day",),
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
    # CR1. Club Waistline: the cropped corset (top-corset-cropped-v1) stops above her waist and
    # is cut higher at the back, so a waistline tattoo has bare skin above the low-rise mini.
    Outfit(
        "club-waistline",
        "Club Waistline",
        "dressy",
        "black cropped corset top + black low-rise pleated mini skirt + black stiletto ankle boots",
        tags=("club", "night", "waistline", "boots"),
    ),
    # OC1. A night out with an edge: leather, a corset over jeans, a catsuit — and boots.
    Outfit(
        "leather-mini-combat",
        "Leather mini & combat boots",
        "dressy",
        "black leather bodycon mini dress + black combat boots",
        tags=("edgy", "night", "boots"),
    ),
    Outfit(
        "corset-slim-jeans",
        "Corset & slim jeans",
        "dressy",
        "black corset top + black slim jeans + black stiletto ankle boots",
        tags=("edgy", "night", "boots"),
    ),
    Outfit(
        "catsuit-boots",
        "Catsuit & over-the-knee boots",
        "dressy",
        "black catsuit + black over-the-knee boots",
        tags=("edgy", "night", "boots"),
    ),
    Outfit(
        "cocktail-stilettos",
        "Cocktail dress & stiletto boots",
        "dressy",
        "black satin cocktail dress + black stiletto ankle boots",
        tags=("evening", "boots"),
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
    # CR1. The same satin mini cut open at the back (the collection's own "Open back" choice),
    # over the over-the-knee boots: her upper back and shoulder blades bare.
    Outfit("discoteca-open-back", "Open-back dress & over-the-knee boots", "discoteca",
           outfit_prompt("sexy-discoteca-black", "over-knee", {"back": "open", "material": "satin"}),
           tags=("party", "night", "boots", "open-back")),
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
    # OC1. Work and campus: a trouser suit, a skirt suit and two preppy sets.
    Outfit(
        "blouse-wide-leg",
        "Blouse & wide-leg trousers",
        "smart",
        "white blouse + navy wide-leg trousers",
        tags=("work",),
    ),
    Outfit(
        "navy-suit",
        "Navy trouser suit",
        "smart",
        "navy blazer + white blouse + navy straight trousers",
        tags=("work", "formal"),
    ),
    Outfit(
        "grey-skirt-suit",
        "Grey skirt suit",
        "smart",
        "grey blazer + white blouse + grey pencil skirt",
        tags=("work", "formal"),
    ),
    Outfit(
        "preppy-a-line",
        "Blouse & A-line skirt",
        "smart",
        "white blouse + navy a-line skirt",
        tags=("preppy",),
    ),
    Outfit(
        "preppy-cardigan",
        "Blouse, cardigan & trousers",
        "smart",
        "white blouse + navy cropped cardigan + grey straight trousers",
        tags=("preppy",),
    ),
    # --- active (OC1) ---------------------------------------------------
    Outfit(
        "gym-cami-leggings", "Cami & leggings", "active", "black cropped cami + black leggings", tags=("gym",)
    ),
    Outfit("gym-tee-leggings", "Tee & leggings", "active", "grey fitted tee + black leggings", tags=("gym",)),
    Outfit(
        "yoga-set", "Lavender yoga set", "active", "lavender cropped cami + lavender leggings", tags=("yoga",)
    ),
    Outfit(
        "athleisure-coat",
        "Coat, tee & leggings",
        "active",
        "black oversized coat + white fitted tee + black leggings",
        tags=("athleisure",),
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
    Outfit(
        "navy-pajamas",
        "Navy pajamas",
        "cozy",
        "navy pajama shirt + navy pajama bottoms",
        tags=("sleep", "comfy"),
    ),
    Outfit("blush-nightgown", "Blush nightgown", "cozy", "blush satin nightgown", tags=("sleep",)),
    Outfit(
        "cozy-lounge",
        "Long cardigan & leggings",
        "cozy",
        "cream long cardigan + white fitted tee + grey leggings",
        tags=("comfy", "sleep"),
    ),
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
    Outfit(
        "cami-wrap-skirt",
        "Camisole & wrap skirt",
        "summer",
        "white camisole top + turquoise wrap skirt",
        tags=("resort",),
    ),
    Outfit(
        "cami-denim-shorts",
        "Cami & denim shorts",
        "summer",
        "white cropped cami + blue denim shorts",
        tags=("beach",),
    ),
    # --- swimwear (private) ---------------------------------------------
    Outfit("triangle-bikini", "Triangle bikini", "swim", "red triangle bikini", tags=("beach",)),
    Outfit("bandeau-bikini", "Bandeau bikini", "swim", "white bandeau bikini", tags=("beach",)),
    Outfit("one-piece", "One-piece swimsuit", "swim", "black one-piece swimsuit", tags=("beach",)),
    Outfit("skirted-swimsuit", "Skirted swimsuit", "swim", "navy skirted swimsuit", tags=("beach",)),
    # --- AN2. Anime fan service ------------------------------------------
    # Original designs in the spirit of well-known anime heroines (docs/ANIME_FAN_SERVICE.md):
    # silhouettes and palettes from the planner's own words, no character's name, logo or
    # artwork. Grouped by the rating Forge computes, as every entry here is: the bikini, the
    # swimsuit worn as a leotard and the bodysuit need an adult declaration; the rest do not.
    Outfit("anime-island-archaeologist", "Island Archaeologist", "anime",
           "purple cropped cami + pink and white floral long wrap skirt with slit",
           tags=("anime-inspired", "fan-service", "beach")),
    Outfit("anime-retro-bounty", "Retro Bounty Hunter", "anime",
           "yellow halter crop top + yellow denim shorts + red cropped jacket worn open"
           " + white over-the-knee boots",
           tags=("anime-inspired", "fan-service", "retro")),
    Outfit("anime-midnight-thief", "Midnight Thief", "anime",
           "black latex catsuit with plunging neckline + black over-the-knee boots",
           tags=("anime-inspired", "fan-service", "catsuit")),
    Outfit("anime-thorn-assassin", "Thorn Assassin", "anime",
           "black satin halter evening gown with thigh slit + black thigh-high stockings"
           " + black stiletto ankle boots",
           tags=("anime-inspired", "fan-service", "glamour")),
    Outfit("anime-serpent-empress", "Serpent Empress", "anime",
           "red and pink floral satin halter evening gown with thigh slit + red stiletto ankle boots",
           tags=("anime-inspired", "fan-service", "glamour")),
    Outfit("anime-abyss-guardian", "Abyss Guardian", "anime",
           "white satin halter evening gown with thigh slit + black stiletto ankle boots",
           tags=("anime-inspired", "fan-service", "fantasy")),
    Outfit("anime-reaper-lieutenant", "Reaper Lieutenant", "anime",
           "black long-sleeve wrap dress with plunging neckline + black wide trousers",
           tags=("anime-inspired", "fan-service", "fantasy")),
    Outfit("anime-rose-commander", "Rose Commander", "anime",
           "pink latex catsuit with plunging neckline + pink over-the-knee boots",
           tags=("anime-inspired", "fan-service", "action")),
    Outfit("anime-ice-general", "Ice General", "anime",
           "white blazer + white mini pencil skirt + black over-the-knee stiletto boots",
           tags=("anime-inspired", "fan-service", "action")),
    Outfit("anime-ocean-navigator", "Ocean Navigator", "anime-private",
           "green and white striped triangle bikini top + low-rise blue jeans",
           tags=("anime-inspired", "fan-service", "beach")),
    Outfit("anime-moon-rabbit", "Moon Rabbit Hero", "anime-private",
           "white high-cut one-piece swimsuit + white over-the-knee boots",
           tags=("anime-inspired", "fan-service", "action")),
    Outfit("anime-ghost-operative", "Ghost Operative", "anime-private",
           "black high-cut bodysuit + black thigh-high stockings + black cropped jacket worn open"
           " + black combat boots",
           tags=("anime-inspired", "fan-service", "action")),
    # --- erotic sets (private, ES3: dressed over her bare body) ------------
    Outfit("erotic-boudoir", "Boudoir garter set", "erotic",
           "black lace balconette bra + black garter set + black thigh-high stockings",
           tags=("boudoir", "striptease", "bedroom"), base="bare-dressed"),
    Outfit("erotic-seduction", "Sheer babydoll & thong", "erotic", "black sheer babydoll + black thong",
           tags=("seduction", "bedroom"), base="bare-dressed"),
    Outfit("erotic-dominant", "Leather corset & garter", "erotic",
           "black structured leather corset + black leather garter + black g-string"
           " + black over-knee boots",
           tags=("dominant", "role-play"), base="bare-dressed"),
    Outfit("erotic-fishnet", "Fishnet bodystocking & heels", "erotic",
           "black fishnet bodystocking + black stiletto heels",
           tags=("club", "tease"), base="bare-dressed"),
    Outfit("erotic-cutout", "Cut-out bodysuit", "erotic", "red cut-out bodysuit + red stiletto heels",
           tags=("date-night", "tease"), base="bare-dressed"),
    Outfit("erotic-massage", "Bralette & thong", "erotic", "white bralette + white thong",
           tags=("massage", "slow", "bedroom"), base="bare-dressed"),
    Outfit("erotic-after-shower", "Short robe & thong", "erotic", "white short robe + white thong",
           tags=("shower", "morning"), base="bare-dressed"),
    Outfit("erotic-guepiere", "Guêpière & stockings", "erotic",
           "black guêpière + black g-string + black thigh-high stockings",
           tags=("striptease", "boudoir"), base="bare-dressed"),
    Outfit("erotic-micro-bikini", "Black micro bikini, poolside", "erotic", "black micro bikini",
           tags=("pool", "sun", "tease"), base="bare-dressed"),
    Outfit("erotic-night-out", "Sheer mini & thong", "erotic",
           "black sheer bodycon mini dress + black thong + black stiletto heels",
           tags=("night-out", "tease"), base="bare-dressed"),
    # --- shows (private, VA4): dressed for the chatbot's Private shows ------------------------
    # The striptease takes three layers off, one look down at a time through her own looks
    # (OutfitDecisionEngine.undressStep in the chatbot): so each set is a pair — the outfit and the
    # lingerie under it, matching — then the lingerie's top alone comes off (`partial`), then bare.
    # Generate both looks of a pair for her; the table-dance looks are one each.
    Outfit("show-strip-red", "Striptease · red slip dress", "erotic",
           "red satin slip dress + red lace balconette bra + red thong + red stiletto heels",
           tags=("striptease", "show", "dressed"), base="bare-dressed"),
    Outfit("show-strip-red-under", "Striptease · red lace underneath", "erotic",
           "red lace balconette bra + red thong + red stiletto heels",
           tags=("striptease", "show", "underneath"), base="bare-dressed"),
    Outfit("show-strip-office", "Striptease · office blouse & pencil skirt", "erotic",
           "white button-up shirt + black pencil skirt + black lace bra + black g-string"
           " + black thigh-high stockings + black stiletto heels",
           tags=("striptease", "show", "dressed", "role-play"), base="bare-dressed"),
    Outfit("show-strip-office-under", "Striptease · black lace & stockings underneath", "erotic",
           "black lace bra + black g-string + black thigh-high stockings + black stiletto heels",
           tags=("striptease", "show", "underneath"), base="bare-dressed"),
    Outfit("show-strip-trench", "Striptease · trench coat & lingerie", "erotic",
           "beige trench coat + black lace lingerie set + black thigh-high stockings + black stiletto heels",
           tags=("striptease", "show", "dressed"), base="bare-dressed"),
    Outfit("show-strip-trench-under", "Striptease · lace set & stockings underneath", "erotic",
           "black lace lingerie set + black thigh-high stockings + black stiletto heels",
           tags=("striptease", "show", "underneath"), base="bare-dressed"),
    Outfit("show-strip-lbd", "Striptease · little black dress", "erotic",
           "black bodycon mini dress + black lace bra + black thong + black stiletto heels",
           tags=("striptease", "show", "dressed"), base="bare-dressed"),
    Outfit("show-strip-lbd-under", "Striptease · black bra & thong underneath", "erotic",
           "black lace bra + black thong + black stiletto heels",
           tags=("striptease", "show", "underneath"), base="bare-dressed"),
    Outfit("show-strip-robe", "Striptease · short robe & garters", "erotic",
           "black short robe + black lace balconette bra + black garter set + black thigh-high stockings",
           tags=("striptease", "show", "dressed", "bedroom"), base="bare-dressed"),
    Outfit("show-strip-robe-under", "Striptease · balconette & garters underneath", "erotic",
           "black lace balconette bra + black garter set + black thigh-high stockings",
           tags=("striptease", "show", "underneath"), base="bare-dressed"),
    Outfit("show-table-sequin", "Table dance · sequin mini & fishnets", "erotic",
           "silver sequin mini dress + black fishnet tights + black stiletto heels",
           tags=("table-dance", "show", "club"), base="bare-dressed"),
    Outfit("show-table-shorts", "Table dance · denim shorts & bralette", "erotic",
           "black denim shorts + black bralette + black ankle boots",
           tags=("table-dance", "show", "club"), base="bare-dressed"),
    Outfit("show-table-lace-body", "Table dance · red lace bodysuit", "erotic",
           "red lace bodysuit + red stiletto heels",
           tags=("table-dance", "show", "tease"), base="bare-dressed"),
    Outfit("show-table-sheer-crop", "Table dance · sheer crop & thong", "erotic",
           "black sheer crop top + black thong + black thigh-high stockings + black stiletto heels",
           tags=("table-dance", "show", "tease"), base="bare-dressed"),
    Outfit("show-table-pink-bikini", "Table dance · pink micro bikini", "erotic",
           "pink micro bikini + white stiletto heels",
           tags=("table-dance", "show", "tease"), base="bare-dressed"),
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
    # CR1. The whale tail with a cropped cami and baggy jeans: the look preset that already
    # existed (visible_thong_cami_baggy_jeans), now a dictionary look.
    Outfit(
        "visible-v-string-y2k",
        "Visible V-string · Y2K",
        "lingerie",
        LOOK_PRESETS["visible_thong_cami_baggy_jeans"]["prompt"],
        preset="visible_thong_cami_baggy_jeans",
        tags=("y2k", "waistline"),
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
    # CR1. Sheer layering over lingerie: the bralette shows through the blouse, as it is meant to.
    Outfit(
        "sheer-blouse-bralette",
        "Sheer blouse over a lace bralette",
        "sheer",
        "black lace bralette + sheer white blouse + black mini skirt",
    ),
    # --- role-play · adults (RP1) -------------------------------------------
    Outfit("roleplay-secretary", "Secretary", "roleplay",
           "white blouse + black pencil skirt + sheer black thigh-high stockings"
           " + black stiletto ankle boots",
           tags=("role-play", "office")),
    Outfit("roleplay-police", "Police officer", "roleplay",
           "navy fitted tee + navy pleated mini skirt + sheer black thigh-high stockings"
           " + black over-the-knee boots",
           tags=("role-play", "uniform")),
    Outfit("roleplay-firefighter", "Firefighter", "roleplay",
           "red corset + black skater mini skirt + sheer black thigh-high stockings"
           " + black over-the-knee boots",
           tags=("role-play", "uniform")),
    Outfit("roleplay-nurse", "Nurse", "roleplay",
           "white bodycon mini dress + sheer white thigh-high stockings + white stiletto ankle boots",
           tags=("role-play", "uniform")),
    Outfit("roleplay-flight-attendant", "Flight attendant", "roleplay",
           "navy blazer + white blouse + navy pencil skirt + sheer nude thigh-high stockings"
           " + navy stiletto ankle boots",
           tags=("role-play", "uniform")),
    # GL1. Glamour editions: the same themes on fitted garments (top-glam-blouse-v1,
    # skirt-glam-pencil-mini-v1, jacket-glam-cropped-v1). The originals above stay as they are.
    Outfit("roleplay-secretary-glam", "Secretary · Glamour", "roleplay",
           "ivory satin fitted v-neck blouse + charcoal pencil mini skirt + sheer black thigh-high stockings"
           " + black stiletto ankle boots",
           tags=("role-play", "office", "glamour")),
    Outfit("roleplay-flight-attendant-glam", "Flight attendant · Glamour", "roleplay",
           "navy fitted cropped jacket + white fitted v-neck blouse + navy pencil mini skirt"
           " + sheer nude thigh-high stockings + navy stiletto ankle boots",
           tags=("role-play", "uniform", "glamour")),
    Outfit("roleplay-firefighter-glam", "Firefighter · Glamour", "roleplay",
           "red satin corset + black satin skater mini skirt + sheer black thigh-high stockings"
           " + black over-the-knee stiletto boots",
           tags=("role-play", "uniform", "glamour")),
)


def _collection_outfits() -> tuple[Outfit, ...]:
    """AB. Every design of every independent collection (wardrobe.collections), as entries.

    Generated from the collection's own record, so a design is described once. Each entry's
    request names the design, so a job for it builds the design's construction; its prompt is
    the pieces' own words, which plan on their own too. In a group of its own per collection:
    nothing here is added to, or changes, an entry above.
    """
    from wardrobe.collections import collections

    out = []
    for collection in collections().values():
        for d in collection["designs"]:
            out.append(Outfit(
                d["id"], f"{d['title']} · {d['subtitle']}", collection["id"],
                " + ".join(p["prompt"] for p in d["pieces"]),
                tags=(collection["id"], d["category"].lower().replace(" ", "-"), "beach"),
                design=(collection["id"], d["id"]),
            ))
    return tuple(out)


def _atelier_outfits() -> tuple[Outfit, ...]:
    """AA. One dictionary look per card the atelier built. The order book is the source."""
    from wardrobe.atelier.orders import built_orders

    return tuple(
        Outfit(order.id, order.title, order.group, order.prompt, tags=order.tags)
        for order in built_orders()
    )


OUTFITS = OUTFITS + _collection_outfits() + _atelier_outfits()


#: CR2. Stockings as an add-on to a look she wears: the request blocks merged into the look's
#: own outfit request (``wardrobe.hosiery``). Hold-ups are stockings alone — the planner adds no
#: belt when none is asked for — so they suit a low-rise look whose bare waist a belt would cover.
HOLD_UPS = {"hosiery": {"type": "sheer", "denier": 15, "color": "black", "topStyle": "wide"}}
SUSPENDERS = {
    "hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "wide"},
    "suspenderBelt": {"style": "classic", "color": "black", "strapCount": 4, "hardware": {"color": "silver"}},
}
STOCKINGS_WORDS = "black sheer thigh-high stockings"
#: What on her makes stockings pointless or impossible: her legs already covered, or a beach.
LEGS_COVERED = frozenset({"trousers", "jumpsuit", "legwear", "nightwear", "swimwear"})


def add_ons(outfit: Outfit, garments: list[dict], catalog: TemplateCatalog) -> list[dict]:
    """CR2. The stockings a look can take, each with the blocks a client merges and its rating.

    Read from what the planner builds, never from the look's name: a skirt or dress has a
    hem the reveal can move (glimpse for hold-ups, the straps below it for suspenders); a look
    of underwear alone takes a garter set in full view; shorts take hold-ups only. Her legs
    already covered (trousers, a catsuit, stockings of her own), swimwear, or over-the-knee
    boots that would hide the tops: none. The rating is the planner's for the merged request,
    as a job's would be — sheer stockings show her body, so they are private.
    """
    from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

    categories = {g["category"] for g in garments}
    if categories & LEGS_COVERED or any("over-knee" in (g["template"] or "") for g in garments):
        return []
    hem = bool(categories & {"dress", "skirt"})
    lingerie = categories == {"underwear"}
    if not (hem or lingerie or "shorts" in categories):
        return []
    glimpse = {"reveal": {"level": "glimpse"}} if hem else {}
    choices = [("hold-ups", "Hold-up stockings", {**HOLD_UPS, **glimpse})]
    if hem or lingerie:
        belt = {**SUSPENDERS["suspenderBelt"], "visibility": "straps_only" if hem else "full"}
        statement = {"reveal": {"level": "statement"}} if hem else {}
        blocks = {**SUSPENDERS, "suspenderBelt": belt, **statement}
        choices.append(("suspenders", "Stockings & suspenders", blocks))
    out = []
    base = outfit.request().model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
    for key, title, blocks in choices:
        # The stockings are named in the prompt as well as set by the blocks: the planner builds
        # the same garments either way, and the look made has a prompt of its own — a client
        # that finds a look by its prompt never mistakes the stockinged one for the plain one.
        request = {**base, **blocks, "prompt": f"{base['prompt']} + {STOCKINGS_WORDS}"}
        plan = plan_outfit_stack(OutfitRequest.model_validate(request), catalog)
        gated = any(g.category in INTIMATE_CATEGORIES or bool(g.requires_adult) for g in plan.garments)
        out.append({"id": key, "title": title, "blocks": blocks, "request": request,
                    "rating": "private" if gated else "general"})
    return out


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
        # CR2. Additive: a client that does not know add-ons ignores the key.
        "addOns": add_ons(outfit, garments, catalog),
        # ES3. Additive too: the job options this entry needs (its base body), and which halves can
        # come off alone — a set with both a top and a bottom piece.
        **({"options": {"baseBody": outfit.base}} if outfit.base else {}),
        **({"partial": _partial(garments)} if outfit.base else {}),
    }


def _partial(garments: list[dict]) -> list[str]:
    """ES3. "top" / "bottom" when the set has a piece that is only that half (a bra, a thong)."""
    halves = set()
    for garment in garments:
        name = (garment.get("template") or "") + " " + garment["name"].lower()
        tops = ("bra", "bralette", "bikini-top", "corset", "guepiere", "guêpière", "bustier", "babydoll")
        if any(k in name for k in tops):
            halves.add("top")
        if any(k in name for k in ("thong", "string", "brief", "garter", "tanga", "cheeky", "bikini-bottom")):
            halves.add("bottom")
    return sorted(halves)


@lru_cache(maxsize=4)
def _catalogue(catalog_id: int, catalog: TemplateCatalog) -> tuple[dict, ...]:
    return tuple(plan_entry(outfit, catalog) for outfit in OUTFITS)


def catalogue(catalog: TemplateCatalog) -> dict:
    """``GET /v1/outfits``: the groups and every entry, planned. Cached per catalogue."""
    from wardrobe.atelier.orders import report as atelier_report
    from wardrobe.pipeline.occasions import catalogue as occasions

    entries = [dict(entry) for entry in _catalogue(id(catalog), catalog)]
    return {
        "version": 1,
        "groups": [{"id": g.id, "title": g.title, "private": g.private} for g in GROUPS],
        "outfits": entries,
        # OC1. Occasion → style → these entries' ids: the Studio's first question. Additive, so
        # a client that reads only groups and outfits is unchanged.
        "occasions": occasions({entry["id"]: entry for entry in entries}),
        # AA. What the atelier built, what is already a prompt, and what still needs a shape.
        # Additive: a client that does not know the key ignores it.
        "atelier": atelier_report(),
    }


__all__ = [
    "GROUPS",
    "HOLD_UPS",
    "OUTFITS",
    "SLOT_OF_CATEGORY",
    "SUSPENDERS",
    "Group",
    "Outfit",
    "add_ons",
    "catalogue",
    "groups",
    "plan_entry",
]
