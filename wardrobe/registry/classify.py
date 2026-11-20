"""WS1. What each garment is, and which collections it belongs in — from its own metadata.

The Studio showed garments by the template catalog's twelve engine categories (``top``,
``underwear``…) and a handful of occasions; nothing answered "show me everything for date night"
or "every corset", and nothing listed a garment that no occasion happened to use. This file
gives every template one primary clothing type (the twenty a person shops by) and any number of
collection memberships, by rules over the template's own id, category and tags — never by
inventing a garment, never by copying one: a membership is a reference to the template id.

Rules, not a model: they are read in review, they say why (``reasons``), and a garment they are
unsure of goes to Needs Review instead of being guessed into a shelf. An admin's own choice
(``wardrobe.registry.store``) always wins over a rule and is never overwritten by one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The twenty primary clothing types, in the order a shop lists them.
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("dresses", "Dresses"),
    ("tops", "Tops & Blouses"),
    ("tshirts", "T-Shirts"),
    ("knitwear", "Sweaters & Cardigans"),
    ("outerwear", "Jackets & Coats"),
    ("trousers", "Jeans & Trousers"),
    ("shorts", "Shorts"),
    ("skirts", "Skirts"),
    ("leggings", "Leggings"),
    ("sets", "Matching Sets"),
    ("formal", "Formalwear & Suits"),
    ("lingerie", "Lingerie & Underwear"),
    ("sleepwear", "Sleepwear & Loungewear"),
    ("swimwear", "Swimwear"),
    ("activewear", "Activewear"),
    ("hosiery", "Stockings & Socks"),
    ("shoes", "Shoes & Boots"),
    ("accessories", "Bags & Accessories"),
    ("costumes", "Cosplay & Costumes"),
    ("outfits", "Complete Outfits"),
)
CATEGORY_IDS = tuple(c for c, _ in CATEGORIES)

#: The engine's template categories that map straight to one primary type.
_BY_ENGINE = {
    "dress": "dresses",
    "skirt": "skirts",
    "shorts": "shorts",
    "shoes": "shoes",
    "legwear": "hosiery",
    "swimwear": "swimwear",
    "underwear": "lingerie",
    "nightwear": "sleepwear",
}


def _has(tags: set[str], *words: str) -> bool:
    return any(w in tags for w in words) or any(any(w in t for t in tags) for w in words if " " not in w)


def primary_type(template_id: str, category: str, tags: set[str]) -> tuple[str | None, str]:
    """The garment's primary type and why; ``None`` when no rule is sure (Needs Review)."""
    if category in _BY_ENGINE:
        return _BY_ENGINE[category], f"engine category {category}"
    if category == "top":
        if "sports bra" in tags or "sport bra" in tags:
            return "activewear", "a sports bra"
        if _has(tags, "tee", "t-shirt"):
            return "tshirts", "a tee"
        return "tops", "a top"
    if category == "jacket":
        if _has(tags, "cardigan", "knitwear"):
            return "knitwear", "a cardigan"
        return "outerwear", "a jacket or coat"
    if category == "trousers":
        if "leggings" in template_id:
            return "leggings", "leggings"
        return "trousers", "trousers or jeans"
    if category == "jumpsuit":
        if "bodystocking" in template_id:
            return "lingerie", "a bodystocking"
        if "latex" in template_id:
            return "costumes", "a latex catsuit"
        # A plain catsuit is clubwear, costume or activewear depending on how it is worn.
        return None, "a catsuit: clubwear, costume or activewear — needs a person's choice"
    return None, f"no rule for engine category {category}"


@dataclass(frozen=True)
class Collection:
    id: str
    title: str
    description: str
    section: str  # discover | occasions | styles | clothing | private | looks
    private: bool = False
    #: Template ids that belong, chosen by hand where tags cannot say it.
    garments: tuple[str, ...] = ()
    #: Tags (any) that make a garment belong.
    tags: tuple[str, ...] = ()
    #: Primary types that belong whole.
    types: tuple[str, ...] = ()
    #: Outfit-dictionary groups whose ready looks belong.
    groups: tuple[str, ...] = ()
    #: Outfit tags (any) that make a ready look belong.
    outfit_tags: tuple[str, ...] = ()
    #: WS2. Body items (``preset:``, ``state:``, ``extra:`` ids) whose id contains any of these.
    body: tuple[str, ...] = ()
    #: Computed by the registry, not by membership rules (all, favourites, review…).
    smart: str | None = None
    extra: dict = field(default_factory=dict)


def _c(id, title, description, section, **kw) -> Collection:
    return Collection(
        id=id,
        title=title,
        description=description,
        section=section,
        **{k: tuple(v) if isinstance(v, list) else v for k, v in kw.items()},
    )


#: Public fashion collections, populated from garments that exist (ids checked by the tests).
PUBLIC = (
    _c(
        "everyday-essentials",
        "Everyday Essentials",
        "Comfortable daily fashion",
        "occasions",
        tags=["everyday"],
        garments=[
            "top-tee-v1",
            "top-fitted-tee-v1",
            "jeans-straight-v1",
            "shoes-flats-v1",
            "trousers-straight-v1",
            "dress-shirt-v1",
            "skirt-a-line-v1",
            "shoes-boots-v1",
            "trousers-slim-v1",
            "shorts-slip-v1",
        ],
        groups=["casual"],
    ),
    _c(
        "casual-chic",
        "Casual Chic",
        "Effortless feminine styling",
        "styles",
        garments=[
            "dress-wrap-sleeve-v1",
            "dress-slip-midi-v1",
            "top-blouse-v1",
            "top-camisole-v1",
            "skirt-wrap-v1",
            "trousers-wide-v1",
            "dress-maxi-sundress-v1",
            "skirt-slip-midi-v1",
            "jacket-cropped-cardigan-v1",
            "top-halter-v1",
        ],
        groups=["casual"],
    ),
    _c(
        "streetwear",
        "Streetwear",
        "Urban and oversized fashion",
        "styles",
        garments=[
            "jeans-baggy-v1",
            "trousers-balloon-v1",
            "jacket-oversized-v1",
            "shoes-combat-boots-v1",
            "top-crop-tee-v1",
            "shoes-platform-boots-v1",
            "top-tee-v1",
            "shorts-denim-v1",
        ],
    ),
    _c(
        "office-business",
        "Office & Business",
        "Professional and smart casual",
        "occasions",
        tags=["work"],
        garments=[
            "jacket-blazer-v1",
            "top-blouse-v1",
            "skirt-pencil-v1",
            "trousers-straight-v1",
            "jacket-trench-v1",
            "dress-shirt-v1",
            "trousers-wide-v1",
            "shoes-flats-v1",
        ],
        groups=["smart"],
    ),
    _c(
        "date-night",
        "Date Night",
        "Romantic outfits",
        "occasions",
        garments=[
            "dress-wrap-sleeve-v1",
            "dress-slip-midi-v1",
            "dress-mini-skater-v1",
            "top-glam-blouse-v1",
            "top-camisole-v1",
            "shoes-stiletto-pumps-v1",
            "skirt-slip-midi-v1",
            "dress-a-line-v1",
            "dress-plunge-mini-v1",
        ],
        groups=["dressy"],
    ),
    _c(
        "night-out",
        "Night Out",
        "Club and party fashion",
        "occasions",
        tags=["party"],
        garments=[
            "dress-mini-bodycon-v1",
            "dress-cocktail-v1",
            "dress-backless-mini-v1",
            "dress-plunge-mini-v1",
            "dress-buckle-leather-mini-v1",
            "jacket-glam-cropped-v1",
            "skirt-glam-pencil-mini-v1",
            "shoes-platform-heels-v1",
            "shoes-stiletto-ankle-boots-v1",
            "shoes-over-knee-boots-v1",
            "top-tube-v1",
            "top-corset-cropped-v1",
            "top-corset-v1",
        ],
        groups=["discoteca"],
    ),
    _c(
        "elegant-evening",
        "Elegant Evening",
        "Formal dresses and eveningwear",
        "occasions",
        tags=["evening", "gown"],
        garments=[
            "dress-evening-column-v1",
            "dress-slit-gown-v1",
            "dress-cocktail-v1",
            "dress-slip-midi-v1",
            "shoes-stiletto-pumps-v1",
            "trousers-wide-v1",
        ],
        groups=["dressy"],
    ),
    _c(
        "old-money",
        "Old Money",
        "Classic luxury styling",
        "styles",
        garments=[
            "jacket-trench-v1",
            "jacket-blazer-v1",
            "dress-a-line-v1",
            "jacket-long-cardigan-v1",
            "trousers-straight-v1",
            "shoes-flats-v1",
            "dress-shirt-v1",
            "skirt-pleated-mini-v1",
            "skirt-pencil-v1",
            "top-blouse-v1",
        ],
    ),
    _c(
        "minimalist",
        "Minimalist",
        "Clean silhouettes and neutral colours",
        "styles",
        garments=[
            "top-fitted-tee-v1",
            "top-tee-v1",
            "dress-slip-midi-v1",
            "jeans-straight-v1",
            "trousers-straight-v1",
            "top-camisole-v1",
            "shoes-flats-v1",
            "skirt-slip-midi-v1",
            "dress-evening-column-v1",
            "trousers-slim-v1",
        ],
    ),
    _c(
        "y2k",
        "Y2K Fashion",
        "Early-2000s trends",
        "styles",
        garments=[
            "top-crop-cami-v1",
            "top-tube-v1",
            "top-halter-v1",
            "jeans-baggy-v1",
            "shoes-platform-boots-v1",
            "skirt-pleated-mini-v1",
            "skirt-skater-mini-v1",
            "top-crop-tee-v1",
            "top-cropped-cami-v1",
            "shoes-platform-heels-v1",
        ],
    ),
    _c(
        "kawaii",
        "Kawaii & Cute",
        "Playful pastel fashion",
        "styles",
        garments=[
            "skirt-pleated-mini-v1",
            "dress-mini-skater-v1",
            "skirt-skater-mini-v1",
            "jacket-cropped-cardigan-v1",
            "shoes-platform-boots-v1",
            "legwear-thigh-highs-v1",
        ],
        groups=["anime"],
    ),
    _c(
        "gothic",
        "Gothic & Alternative",
        "Dark and edgy fashion",
        "styles",
        garments=[
            "shoes-combat-boots-v1",
            "dress-buckle-leather-mini-v1",
            "top-corset-v1",
            "shoes-platform-boots-v1",
            "jumpsuit-high-neck-latex-v1",
            "legwear-tights-v1",
            "shoes-over-knee-boots-v1",
            "top-corset-cropped-v1",
            "skirt-glam-pencil-mini-v1",
        ],
    ),
    _c(
        "sport-fitness",
        "Sport & Fitness",
        "Training and activewear",
        "occasions",
        types=["activewear", "leggings"],
        garments=["top-tee-v1", "top-crop-tee-v1"],
        groups=["active"],
    ),
    _c(
        "summer-beach",
        "Summer & Beach",
        "Summer clothing and swimsuits",
        "occasions",
        tags=["summer", "beach", "vacation"],
        garments=[
            "dress-maxi-sundress-v1",
            "skirt-maxi-v1",
            "shorts-linen-v1",
            "shorts-denim-v1",
            "top-halter-v1",
            "skirt-tiered-maxi-v1",
        ],
        types=["swimwear"],
        groups=["summer", "swim"],
    ),
    _c(
        "autumn-winter",
        "Autumn & Winter",
        "Coats, knitwear, layered fashion",
        "occasions",
        tags=["winter"],
        types=["knitwear", "outerwear"],
        garments=[
            "shoes-boots-v1",
            "legwear-tights-v1",
            "jeans-straight-v1",
            "shoes-combat-boots-v1",
            "shoes-over-knee-boots-v1",
        ],
    ),
    _c(
        "cozy-home",
        "Cozy & Home",
        "Relaxed home outfits",
        "occasions",
        tags=["cozy", "lounge"],
        types=["sleepwear"],
        garments=["jacket-long-cardigan-v1", "jacket-oversized-v1", "top-tee-v1"],
        groups=["cozy"],
    ),
    _c(
        "festival",
        "Festival & Concert",
        "Expressive fashion",
        "styles",
        garments=[
            "shorts-denim-v1",
            "top-crop-tee-v1",
            "top-halter-v1",
            "shoes-combat-boots-v1",
            "skirt-tiered-maxi-v1",
            "shoes-platform-boots-v1",
            "top-crop-cami-v1",
            "top-cropped-cami-v1",
        ],
    ),
    _c(
        "cosplay-fantasy",
        "Cosplay & Fantasy",
        "Character costumes",
        "styles",
        types=["costumes"],
        garments=["jumpsuit-catsuit-v1", "skirt-pleated-mini-v1", "legwear-thigh-highs-v1"],
        groups=["anime"],
    ),
    _c(
        "editorial",
        "Editorial Fashion",
        "Creative designer styling",
        "styles",
        garments=[
            "trousers-balloon-v1",
            "jacket-trench-v1",
            "dress-slit-gown-v1",
            "dress-evening-column-v1",
            "jacket-glam-cropped-v1",
            "top-structured-leather-corset-v1",
            "shoes-over-knee-stiletto-boots-v1",
            "trousers-wide-v1",
        ],
    ),
    _c("complete-looks", "Complete Looks", "Ready-made outfit combinations", "looks", smart="looks-public"),
)

#: The admin's private wardrobe: never listed, counted or served to anyone else (the API checks).
#: WS1/WS2. Adult: what Private offered before, open to every viewer exactly as it was (the
#: product's choice) and called Adult in the wardrobe. Not too strong: lingerie, erotic sets, shows.
ADULT = (
    _c(
        "adult-atelier",
        "Adult Atelier",
        "The adult atelier cards, built and ready",
        "adult",
        groups=["atelier"],
    ),
    _c(
        "after-dark",
        "After Dark",
        "Clubwear and bold nightlife outfits",
        "adult",
        garments=[
            "jumpsuit-high-neck-latex-v1",
            "jumpsuit-bodystocking-v1",
            "dress-sheer-mini-v1",
            "shoes-over-knee-stiletto-boots-v1",
            "under-leather-garter-v1",
            "top-structured-leather-corset-v1",
            "dress-plunge-mini-v1",
            "dress-backless-mini-v1",
            "shoes-stiletto-ankle-boots-v1",
        ],
        groups=["discoteca", "erotic"],
    ),
    _c(
        "intimates-lingerie",
        "Intimates & Lingerie",
        "Underwear sets, bodysuits and lingerie",
        "adult",
        types=["lingerie"],
        groups=["lingerie"],
    ),
    _c(
        "corsetry-shapewear",
        "Corsetry & Shapewear",
        "Corsets and structured garments",
        "adult",
        garments=[
            "top-corset-v1",
            "top-corset-cropped-v1",
            "top-structured-leather-corset-v1",
            "under-guepiere-v1",
            "under-waspie-v1",
            "under-garter-set-v1",
            "under-suspender-belt-v1",
            "under-suspender-belt-high-v1",
            "under-leather-garter-v1",
        ],
    ),
    _c(
        "sheer-layering",
        "Sheer & Layering",
        "Mesh, transparent fabrics and stockings",
        "adult",
        types=["hosiery"],
        garments=[
            "dress-sheer-mini-v1",
            "jumpsuit-bodystocking-v1",
            "top-crop-cami-v1",
            "under-chemise-satin-v1",
            "night-babydoll-v1",
        ],
        groups=["sheer", "legwear"],
    ),
    _c(
        "try-on-haul",
        "Try-On Haul",
        "Intimate try-on haul pieces, to test and compare",
        "adult",
        types=["shorts", "swimwear", "lingerie", "sleepwear", "hosiery"],
        smart="haul",
    ),
    _c(
        "swimwear-resort",
        "Swimwear & Resort",
        "Bikinis, swimwear and beach looks",
        "adult",
        types=["swimwear"],
        groups=["swim", "anime-beachwear"],
    ),
    _c(
        "fashion-experiments",
        "Fashion Experiments",
        "Unusual and creative combinations",
        "adult",
        groups=["anime-private"],
        garments=["jumpsuit-catsuit-v1", "jumpsuit-high-neck-latex-v1", "trousers-balloon-v1"],
    ),
    _c(
        "erotic-sets",
        "Erotic Sets",
        "Intimate combinations for love and sex, over her bare body",
        "adult",
        groups=["erotic"],
    ),
    # WS1. Aligned with the 3D Avatar Chatbot's Private experience: its shows (UN36/VA3), undressing
    # one layer at a time (UN1, an outfit's `partial` states), its bedroom moments and role-play,
    # and the bare body Forge paints (BD). The same outfit ids the chatbot's Private plays.
    _c(
        "striptease-show",
        "Striptease Show",
        "Dressed and underneath pairs for the striptease, layer by layer",
        "adult",
        outfit_tags=["striptease"],
    ),
    _c(
        "table-dance",
        "Table Dance",
        "Club looks for the table dance that ends astride them",
        "adult",
        outfit_tags=["table-dance"],
    ),
    _c(
        "bedroom-boudoir",
        "Bedroom & Boudoir",
        "Boudoir, seduction, massage and after-shower sets",
        "adult",
        outfit_tags=["bedroom", "boudoir", "massage", "shower"],
    ),
    _c(
        "role-play",
        "Role-Play",
        "Uniforms and characters for role-play",
        "adult",
        groups=["roleplay"],
        outfit_tags=["role-play", "dominant"],
    ),
    _c(
        "undress-step-by-step",
        "Undress Step by Step",
        "Looks that come off one layer at a time — top first or bottom first — as Private undresses her",
        "adult",
        smart="partial",
    ),
)

#: WS2. Private: the admin's alone — her naked body and its sexual states (open, gaped, cum,
#: by position), marks and piercings, and the admin's own tools. Never listed, counted or served
#: to anyone else: the registry leaves these out of every non-admin answer.
PRIVATE = (
    # WS2. Her naked body and its sexual states (Forge's body detail, BD1–BD20): admin only.
    _c(
        "naked-skin",
        "Naked & Skin",
        "Her bare body and the skin presets it is painted with",
        "private",
        private=True,
        smart="bare",
        body=["preset:"],
    ),
    _c(
        "open-gaped",
        "Open & Gaped",
        "Open, gaped, stretched, pumped and fisted states",
        "private",
        private=True,
        body=["open", "gap", "stretch", "pumped", "fisted"],
    ),
    _c(
        "cum-finishes",
        "Cum & Finishes",
        "Cum and creampie, on her and in her, by where they finished",
        "private",
        private=True,
        body=["cum", "creampie", "finish", "covered", "-belly", "-chest", "everything", "-after", "second"],
    ),
    _c(
        "doggy",
        "Doggy",
        "On all fours: her back, lower back and both holes",
        "private",
        private=True,
        body=["state:doggy-", "state:lower-back-", "state:cum-on-back", "state:anal-"],
    ),
    _c(
        "missionary",
        "Missionary",
        "On her back, knees up",
        "private",
        private=True,
        body=["state:missionary-"],
    ),
    _c("cowgirl", "Cowgirl", "Riding them", "private", private=True, body=["state:cowgirl-"]),
    _c(
        "sado",
        "Sado",
        "Roped, wax, whipped and used",
        "private",
        private=True,
        body=["state:sado-", "extra:spanked"],
    ),
    _c(
        "arousal-afterglow",
        "Arousal & Afterglow",
        "Aroused, flushed, sweaty, oiled and the afterglow",
        "private",
        private=True,
        body=["aroused", "flushed", "goosebumps", "sweaty", "afterglow", "oiled", "state:closed"],
    ),
    _c(
        "marks-tattoos-piercings",
        "Tattoos, Piercings & Marks",
        "Intimate tattoos, piercings, kisses, writing, tan lines and glitter",
        "private",
        private=True,
        body=["extra:"],
    ),
    _c(
        "personal-favorites",
        "Personal Favorites",
        "Saved favourite garments",
        "private",
        private=True,
        smart="favourites",
    ),
    _c(
        "exclusive-imports",
        "Exclusive Imports",
        "Newly imported private garments",
        "private",
        private=True,
        smart="private-imports",
    ),
    _c(
        "archive-vintage",
        "Archive & Vintage",
        "Older and archived fashion assets",
        "private",
        private=True,
        smart="superseded",
        garments=["swim-skirted-v1", "under-high-waist-briefs-v2"],
    ),
    _c(
        "private-outfit-lab",
        "Private Outfit Lab",
        "Custom look building and testing",
        "private",
        private=True,
        smart="lab",
    ),
    _c(
        "unsorted-private",
        "Unsorted Private Assets",
        "Private items awaiting organisation",
        "private",
        private=True,
        smart="unsorted-private",
    ),
)

#: WS3. The admin's body catalogue by category, the way the top-rated adult sites file their
#: content: body type and grooming, close-ups, acts, finishes, fetish, decoration. The position
#: collections above (doggy, missionary, cowgirl) say WHERE a state happens; these say WHAT it is,
#: which is how an admin looks for one ("a creampie", "tattooed", "hairy"). Together they cover
#: every preset, state and extra (tests/unit/test_wardrobe_registry.py holds that). A pattern
#: ending in ``$`` is an exact id: ``preset:natural`` alone would also catch ``natural-hair``.
PRIVATE_CATEGORIES = tuple(
    _c(cid, title, description, "private-categories", private=True, body=body)
    for cid, title, description, body in (
        ("cat-shaved-smooth", "Shaved & Smooth", "Bare, smooth skin presets",
         ["preset:natural$", "preset:soft-pink$", "preset:warm$", "preset:defined$", "preset:outie$",
          "preset:puffy$", "preset:porcelain$"]),
        ("cat-natural-hairy", "Natural & Hairy", "Natural hair, trimmed, landing strip, triangle",
         ["preset:natural-hair", "preset:trimmed", "preset:landing-strip", "preset:triangle",
          "preset:auburn-natural"]),
        ("cat-pale-porcelain", "Pale & Porcelain", "Pale and porcelain skin", ["preset:porcelain$"]),
        ("cat-anime-hentai", "Anime & Hentai Style", "The anime-styled body detail", ["preset:anime"]),
        ("cat-solo-tease", "Solo & Tease", "Her body at rest, aroused, flushed, wet",
         ["state:closed$", "state:aroused$", "state:flushed$", "state:goosebumps$", "state:edge$"]),
        ("cat-pussy-closeup", "Pussy Close-ups", "Open, spread, wet and pumped",
         ["state:open$", "state:wide-open$", "state:pumped$", "state:pumped-open$", "state:oiled-aroused$",
          "state:missionary-open$", "state:cowgirl-riding$"]),
        ("cat-anal", "Anal", "Her anus open, stretched, filled and fisted",
         ["anus-", "anal-", "state:both-open$", "-fisted-anal"]),
        ("cat-gaping", "Gaping & Stretched", "Gaping, stretched and wide open",
         ["gaping", "stretched", "state:wide-open$", "state:both-open$", "state:doggy-sweaty-open$"]),
        ("cat-creampie", "Creampie", "Every creampie, inside and dripping", ["creampie", "state:dripping$"]),
        ("cat-cumshot", "Cumshot & Cum on Body", "On her back, belly, chest and all over",
         ["state:cum$", "cum-on-back", "lower-back-cum", "-belly", "-chest", "-covered", "-everything",
          "doggy-finish", "doggy-open-cum", "doggy-gaping-cum", "sado-used-cum", "fisted-cum",
          "cowgirl-after"]),
        ("cat-fisting", "Fisting", "Fisted, vaginal and anal", ["fisted"]),
        ("cat-bdsm", "BDSM & Rough", "Roped, wax, whipped, spanked and used",
         ["state:sado-", "extra:spanked", "state:tied-edge$"]),
        ("cat-oiled-wet", "Oiled, Sweaty & Wet", "Oiled, sweaty and glistening",
         ["oiled", "sweaty", "state:afterglow$"]),
        ("cat-after-sex", "After Sex", "Afterglow and what is left on her",
         ["state:afterglow$", "cowgirl-after", "second", "sado-full", "state:after-shower$",
          "state:round-three$", "state:used$"]),
        ("cat-tattooed", "Tattooed", "Intimate and lower-back tattoos", ["extra:tattoo-"]),
        ("cat-pierced", "Pierced", "Nipple, intimate and full piercings", ["extra:piercings-"]),
        ("cat-tan-lines", "Tan Lines", "Bikini and thong tan lines", ["extra:tan-"]),
        ("cat-love-marks", "Love Marks & Body Writing", "Lipstick kisses, love bites, written words",
         ["extra:kisses-", "extra:love-bites", "extra:writing-", "extra:hearts"]),
        ("cat-glitter-paint", "Glitter & Body Paint", "Glitter and gold body paint",
         ["extra:glitter", "extra:body-paint"]),
        ("cat-natural-body", "Natural Body", "Freckles and stretch marks",
         ["extra:freckles", "extra:stretch-marks"]),
        # By position: where it happens (the chatbot's Private positions).
        ("cat-pos-doggy", "Position · Doggy", "From behind: her back, her ass, both holes",
         ["state:doggy-", "state:lower-back-", "state:cum-on-back$", "state:anal-creampie$"]),
        ("cat-pos-missionary", "Position · Missionary", "On her back, knees up", ["state:missionary-"]),
        ("cat-pos-cowgirl", "Position · Cowgirl", "Riding them", ["state:cowgirl-"]),
        ("cat-pos-bdsm", "Position · Tied & Used", "Roped, waxed, whipped", ["state:sado-"]),
        # By finish: where they finished.
        ("cat-finish-inside", "Finish · Inside", "Creampies, vaginal and anal",
         ["creampie", "state:dripping$"]),
        ("cat-finish-back", "Finish · On Her Back & Ass", "Cum on her back and lower back",
         ["cum-on-back", "lower-back-cum", "doggy-cum-covered", "doggy-finish"]),
        ("cat-finish-belly", "Finish · On Her Belly", "Cum on her belly", ["-belly"]),
        ("cat-finish-chest", "Finish · On Her Chest", "Cum on her breasts", ["-chest"]),
        ("cat-finish-all-over", "Finish · All Over", "Covered, everything, used",
         ["-covered", "-everything", "sado-used-cum", "sado-full", "state:cum$", "state:used$",
          "state:round-three$", "state:breasts-belly$"]),
        ("cat-finish-open", "Finish · Open & Dripping", "Cum with her open or gaping",
         ["doggy-open-cum", "doggy-gaping-cum", "lower-back-cum-open", "lower-back-cum-gaping",
          "fisted-cum"]),
        # The admin's picks: the most explicit of everything, and the slow, sensual end.
        ("cat-most-erotic", "Most Erotic · Hardcore", "The most explicit: gaping, fisted, double, covered",
         ["state:doggy-double-creampie$", "state:doggy-gaping-cum$", "state:doggy-both-fisted$",
          "state:doggy-anal-fisted-cum$", "state:missionary-fisted-cum$", "state:sado-full$",
          "state:sado-used-cum$", "state:cowgirl-everything$", "state:missionary-covered$",
          "state:lower-back-cum-gaping$", "state:both-open$", "state:wide-open$", "state:used$",
          "state:round-three$"]),
        # AB1. The named bare looks of After Dark (each one preset + state + extras), so every body
        # item is in a category; by chapter they are in After Dark · Bare.
        ("cat-bare-looks", "Bare Looks · After Dark", "Named bare looks, from ready to ruined", ["look:"]),
        ("cat-sensual", "Sensual & Elegant", "Aroused, oiled, glowing — the slow end of the evening",
         ["state:aroused$", "state:flushed$", "state:oiled$", "state:oiled-aroused$", "state:afterglow$",
          "extra:tan-", "extra:kisses-", "extra:glitter", "extra:body-paint-gold"]),
    )
)

def _after_dark_bare() -> tuple:
    """AB1. After Dark · Bare: every named bare look, then one collection per chapter of the evening.

    Read from ``assets/body_detail/bare_looks.json`` through its loader, so a look Forge cannot
    paint never makes a collection. Private, in a section of its own that (like every section
    starting "private") is never sent to a guest; an admin or a read grant sees it.
    """
    from wardrobe.registry import bare_looks

    data = bare_looks.load()
    looks = data["looks"]
    out = [
        _c("ad-bare", "After Dark · Bare", "Every bare look, from ready to ruined", "private-after-dark",
           private=True, body=["look:"]),
    ]
    for chapter in data["chapters"]:
        ids = [f"look:{k}$" for k, v in looks.items() if v["chapter"] == chapter["id"]]
        if ids:
            out.append(
                _c(
                    f"ad-bare-{chapter['id']}",
                    f"Bare {chapter['title']}",
                    chapter.get("description", ""),
                    "private-after-dark",
                    private=True,
                    body=ids,
                )
            )
    return tuple(out)


AFTER_DARK_BARE = _after_dark_bare()

#: Computed collections every viewer has (their contents are filtered by what they may see).
SMART = (
    _c("all-clothes", "All Clothes", "Every garment in the wardrobe", "discover", smart="all"),
    _c("recently-added", "Recently Added", "The newest garments", "discover", smart="recent"),
    _c("favorites", "Favorites", "Your saved favourites", "discover", smart="favourites"),
    _c("ready-to-wear", "Ready to Wear", "Pictured and ready to try on", "discover", smart="ready"),
    _c(
        "needs-fit-testing",
        "Needs Fit Testing",
        "Not yet pictured or fit-checked",
        "discover",
        smart="untested",
    ),
    _c("unassigned", "Unassigned", "In no curated collection yet", "discover", smart="unassigned"),
    _c("needs-review", "Needs Review", "The rules were not sure what these are", "discover", smart="review"),
)

ALL = SMART + PUBLIC + ADULT + PRIVATE + PRIVATE_CATEGORIES + AFTER_DARK_BARE
BY_ID = {c.id: c for c in ALL}

SECTIONS = (
    ("discover", "Discover"),
    ("occasions", "Occasions"),
    ("styles", "Styles"),
    ("clothing", "Clothing"),
    ("looks", "My Looks"),
    ("adult", "Adult"),
    ("private", "Private"),
    # WS3. The admin's body catalogue by category; like every section starting "private", never
    # sent to anyone else.
    ("private-categories", "Private · Categories"),
    # AB1. The named bare looks of After Dark, by chapter of the evening (admin or grant only).
    ("private-after-dark", "After Dark · Bare"),
)


def base_name(template_id: str) -> str:
    """``under-bralette-v2`` → ``under-bralette``: the garment without its version."""
    head, _, tail = template_id.rpartition("-v")
    return head if tail.isdigit() else template_id


def suspected_duplicates(items: list[dict]) -> list[list[str]]:
    """Garments that look like the same piece twice: versions of one base name, or names that
    differ only by "crop"/"cropped". Reported for a person to decide; never merged or hidden."""
    groups: dict[str, list[str]] = {}
    for item in items:
        key = base_name(item["id"]).replace("cropped-", "crop-")
        groups.setdefault(key, []).append(item["id"])
    return sorted(sorted(ids) for ids in groups.values() if len(ids) > 1)


__all__ = [
    "ADULT",
    "ALL",
    "BY_ID",
    "CATEGORIES",
    "CATEGORY_IDS",
    "Collection",
    "PRIVATE",
    "PRIVATE_CATEGORIES",
    "PUBLIC",
    "SECTIONS",
    "SMART",
    "base_name",
    "primary_type",
    "suspected_duplicates",
]
