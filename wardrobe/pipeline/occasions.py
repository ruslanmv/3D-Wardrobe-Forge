"""OC1. Occasions: where she is going, before what she is wearing.

The Studio used to open on the garment designer — category, template, silhouette, finish,
coverage, opacity — which is how the Forge thinks, not how anyone getting dressed does.
Nobody plans a night out as "a bodycon one-piece in satin with spaghetti straps"; they
plan a night out. So the first question is the occasion, then a style within it, then a
handful of looks, and the designer is one tap away for whoever wants it.

This module is that menu and nothing else. An occasion holds styles, a style holds looks,
and a look is an id from the outfit dictionary (``wardrobe.pipeline.outfit_dictionary``):
the dictionary already says what the planner builds for each prompt and rates it the way
the job's gate does, so an occasion can neither offer something the Forge cannot make nor
mislabel who may wear it. ``tests/unit/test_occasions.py`` holds both to that.

Privacy is a property of each look, not of the occasion it is listed under, because the
two are different questions: a bikini is *Vacation* and *private*, a corset top is *Night
out* and *general*. A client shows a private-rated look only where private mode is on for
the avatar (the same ``depictsAdult`` the job's gate reads), hides a style left with no
looks, and hides an occasion left with no styles. One occasion, *Private*, is private as a
whole (``private=True``): it is not shown at all without private mode — never as a locked
tile — whatever the rating of the looks inside it, because what it is for is the private
experience. Nothing here grants anything: a look is still planned, fitted and gated as if
its prompt had been typed, and the server refuses what the avatar may not wear.

Tattoos are not an occasion. Whether there is skin to put one on is known only once the
outfit exists (docs/BODY_ART_PLAN.md), so a client offers body art after a look is made,
from that look's exposure, never as a tile beside Work and Gym.

A job may say which occasion and style it was made for (``options.occasion``). The tag is
kept on the look in her wardrobe so the shelf can group by occasion; it is checked against
this catalogue and dropped, not refused, when it names nothing here — a label is not worth
failing a fitted outfit over.
"""

from __future__ import annotations

from dataclasses import dataclass

from wardrobe.domain.garments import TemplateCatalog

#: CR1. The five shots a try-on haul is filmed in, in order: the Studio's shot bar.
SHOTS = ("front", "three-quarter", "back", "detail", "turntable")
#: What a "detail" shot frames.
DETAILS = ("waist", "back", "boots", "legs", "construction")

#: CR1. Body-art moods: the catalogue's designs grouped by the fashion they suit. A mood is a
#: way to *suggest*; it never applies anything (see the module docstring).
BODY_ART_MOODS: dict[str, tuple[str, tuple[str, ...]]] = {
    "y2k": ("Y2K / playful", ("tribal-butterfly-01", "neotribal-heart-01", "heart-stars-01")),
    "romantic": ("Romantic / lingerie", ("rose-vine-01", "ornamental-butterfly-01", "lotus-ornament-01")),
    "dark-club": ("Dark club / edgy", ("thorn-vine-01", "tribal-wings-01", "v-tribal-01")),
    "luxury": ("Luxury / ornamental", ("waist-filigree-01", "dragonfly-01", "lace-ornament-01")),
    "soft-glamour": ("Soft glamour", ("angel-wings-01", "nape-crescent-01")),
}


@dataclass(frozen=True)
class ContentProfile:
    """CR1. How a style is filmed, and the body art it suggests — metadata, never behaviour.

    ``body_art_placements`` and ``body_art_designs`` are *recommendations*, best first. A
    client offers one only after the look exists and ``GET …/looks/{id}/exposure`` says the
    placement is bare on the finished outfit: an outfit's words never decide that.
    """

    shots: tuple[str, ...] = SHOTS
    detail: str = "back"
    body_art_placements: tuple[str, ...] = ()
    body_art_designs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "shots": list(self.shots),
            "detail": self.detail,
            "bodyArt": {"placements": list(self.body_art_placements), "designs": list(self.body_art_designs)},
        }


def _profile(detail: str, placements: tuple[str, ...], designs: tuple[str, ...],
             shots: tuple[str, ...] = SHOTS) -> ContentProfile:
    return ContentProfile(shots=shots, detail=detail, body_art_placements=placements,
                          body_art_designs=designs)


@dataclass(frozen=True)
class Style:
    id: str
    title: str
    icon: str
    blurb: str
    #: Outfit dictionary ids, best first: the first is what a tap on the style card shows.
    looks: tuple[str, ...]
    #: A fashion collection (wardrobe.pipeline.fashion_collections) whose pieces can be swapped
    #: on a look of this style — Discoteca's four boots.
    collection: str | None = None
    #: CR1. How it is filmed and what body art suits it; absent, a style has neither.
    content: ContentProfile | None = None


@dataclass(frozen=True)
class Occasion:
    id: str
    title: str
    icon: str
    #: What the style picker asks once the occasion is chosen.
    question: str
    styles: tuple[Style, ...]
    #: Hidden as a whole without private mode, whatever its looks are rated.
    private: bool = False


OCCASIONS: tuple[Occasion, ...] = (
    Occasion(
        "night-out",
        "Night out",
        "🪩",
        "What kind of night?",
        (
            Style(
                "discoteca",
                "Discoteca",
                "💃",
                "Black mini + boots",
                (
                    "discoteca-stiletto-ankle",
                    "discoteca-platform",
                    "discoteca-combat",
                    "discoteca-over-knee",
                ),
                collection="sexy-discoteca-black",
            ),
            Style(
                "elegant",
                "Elegant",
                "✨",
                "Satin and long lines",
                ("little-black-dress", "slip-dress", "evening-gown", "wrap-dress", "cocktail-stilettos"),
            ),
            Style(
                "party",
                "Party",
                "🎉",
                "Short, bright, fun",
                ("red-bodycon", "skater-dress", "halter-skater", "corset-mini"),
            ),
            Style(
                "edgy",
                "Edgy",
                "🖤",
                "Leather and boots",
                ("leather-mini-combat", "corset-slim-jeans", "catsuit-boots"),
            ),
        ),
    ),
    # CR1. Why the outfit is being made rather than where she is going: a try-on haul is
    # filmed. Each style is a complete look recipe plus how to film it and the body art it
    # suits. Its private styles show only with private mode on, by their looks' ratings.
    Occasion(
        "creator",
        "Try-on haul",
        "🎥",
        "What are you filming?",
        (
            Style("club-waistline", "Club Waistline", "🖤", "Cropped corset, low-rise mini",
                  ("club-waistline",),
                  content=_profile("waist", ("waistline", "lower-back"),
                                   ("waist-filigree-01", "neotribal-heart-01"))),
            Style("y2k-low-rise", "Y2K Low Rise", "🦋", "Cropped cami, low-rise baggy jeans",
                  ("y2k-low-rise",),
                  content=_profile("waist", ("waistline", "lower-back"),
                                   ("tribal-butterfly-01", "heart-stars-01"))),
            Style("discoteca-open-back", "Discoteca Open Back", "🪩", "Open-back satin mini, OTK boots",
                  ("discoteca-open-back",), collection="sexy-discoteca-black",
                  content=_profile("back", ("upper-back", "left-shoulder-blade", "right-shoulder-blade"),
                                   ("tribal-wings-01", "lace-ornament-01"))),
            Style("leather-edge", "Leather Edge", "⛓️", "Leather mini, combat boots",
                  ("leather-mini-combat",),
                  content=_profile("boots", ("lower-back", "left-shoulder-blade", "right-shoulder-blade",
                                             "nape"),
                                   ("thorn-vine-01", "flame-01", "nape-crescent-01"))),
            Style("boots-haul", "Boots Haul", "👢", "One dress, four boots",
                  ("discoteca-stiletto-ankle", "discoteca-platform", "discoteca-combat",
                   "discoteca-over-knee"), collection="sexy-discoteca-black",
                  content=_profile("boots", ("nape", "upper-back"), ("nape-crescent-01", "tribal-wings-01"))),
            Style("visible-v-string", "Visible V-String Y2K", "✨", "Whale tail over baggy jeans",
                  ("visible-v-string-y2k",),
                  content=_profile("waist", ("waistline", "lower-back"),
                                   ("tribal-butterfly-01", "neotribal-heart-01"))),
            Style("italian-lace-thong", "Italian Lace Thong", "🖤", "Lace bralette and thong",
                  ("italian-lace-thong",),
                  content=_profile("back", ("waistline", "lower-back", "upper-back"),
                                   ("rose-vine-01", "ornamental-butterfly-01"))),
            Style("italian-lace-brazilian", "Italian Lace Brazilian", "🌸", "Lace bralette and Brazilian",
                  ("italian-lace-brazilian",),
                  content=_profile("waist", ("waistline", "lower-back", "upper-back"),
                                   ("lotus-ornament-01", "dragonfly-01"))),
            Style("plunge-thong", "Plunge + Thong", "🤍", "White plunge bra and thong",
                  ("plunge-thong",),
                  content=_profile("back", ("waistline", "lower-back", "upper-back"),
                                   ("angel-wings-01", "heart-stars-01"))),
            Style("corsetry", "Corsetry", "🎀", "Guêpière and bodysuit",
                  ("guepiere", "bodysuit"),
                  content=_profile("construction", ("upper-back", "spine-upper", "nape"),
                                   ("lace-ornament-01", "spine-vine-01"))),
            Style("stockings-editorial", "Stockings Editorial", "💋", "Mini and stockings",
                  ("stockings-mini-dress", "fishnets-mini"),
                  content=_profile("legs", ("upper-back", "lower-back", "nape"),
                                   ("lace-ornament-01", "rose-vine-01", "nape-crescent-01"))),
            Style("sheer-layering", "Sheer Layering", "🫧", "Sheer blouse over a mini",
                  ("sheer-blouse",),
                  content=_profile("construction", ("nape", "upper-back"),
                                   ("nape-crescent-01", "lace-ornament-01"))),
        ),
    ),
    Occasion(
        "work",
        "Work",
        "💼",
        "What kind of day at work?",
        (
            Style("office", "Office", "🗂️", "Blouse and tailoring", ("blouse-pencil", "blazer-trousers")),
            Style(
                "smart-casual",
                "Smart casual",
                "☕",
                "Polished, not stiff",
                ("shirt-dress", "blouse-wide-leg", "trench-jeans"),
            ),
            Style(
                "business", "Business", "📊", "A suit for the big meeting", ("navy-suit", "grey-skirt-suit")
            ),
        ),
    ),
    Occasion(
        "gym",
        "Gym",
        "🏋️",
        "What's the workout?",
        (
            Style(
                "training",
                "Training",
                "💪",
                "Fitted, ready to move",
                ("gym-cami-leggings", "gym-tee-leggings"),
            ),
            Style("yoga", "Yoga", "🧘", "Soft and stretchy", ("yoga-set", "leggings-cardigan")),
            Style(
                "athleisure", "Athleisure", "👟", "From the gym to coffee", ("athleisure-coat", "cozy-lounge")
            ),
        ),
    ),
    Occasion(
        "sleep",
        "Sleep",
        "🌙",
        "Ready for bed?",
        (
            Style("pajamas", "Pajamas", "🩷", "Classic button-up sets", ("pajamas", "navy-pajamas")),
            Style("nightgown", "Nightgown", "🌙", "Satin and simple", ("nightgown", "blush-nightgown")),
            Style("cozy", "Cozy", "☁️", "Knit layers for the sofa", ("cozy-lounge", "cardigan-trousers")),
        ),
    ),
    Occasion(
        "shopping",
        "Shopping",
        "🛍️",
        "What's the vibe?",
        (
            Style(
                "casual",
                "Casual",
                "👕",
                "Tee, jeans, done",
                ("tee-jeans", "crop-top-jeans", "denim-shorts", "cami-wide-leg"),
            ),
            Style(
                "streetwear",
                "Streetwear",
                "🧢",
                "Oversized and baggy",
                ("street-coat-baggy", "tube-top-baggy-jeans", "cami-balloon"),
            ),
            Style(
                "cute",
                "Cute",
                "🎀",
                "Skirts and soft colours",
                ("pleated-cardigan", "skater-dress", "halter-skater"),
            ),
        ),
    ),
    Occasion(
        "vacation",
        "Vacation",
        "🌴",
        "Where are we headed?",
        (
            Style(
                "resort",
                "Resort",
                "🍹",
                "Light and breezy",
                ("yellow-sundress", "cami-wrap-skirt", "linen-shorts"),
            ),
            # The swimwear here is private-rated and shows only with private mode on; the cami and
            # shorts are what everyone else sees, so the style never appears empty.
            Style(
                "beach",
                "Beach",
                "🏖️",
                "Sun, sand, swim",
                (
                    "cami-denim-shorts",
                    "triangle-bikini",
                    "bandeau-bikini",
                    "one-piece",
                    "skirted-swimsuit",
                    "beach-ocean-stripe",
                    "beach-sakura-ties",
                    "beach-midnight-string",
                    "beach-violet-halter",
                    "beach-sunset-bandeau",
                    "beach-pearl-bandeau",
                    "beach-scarlet-scoop",
                    "beach-indigo-highcut",
                    "beach-noir-cutout",
                    "beach-rose-ruffle",
                    "beach-aqua-skirt",
                    "beach-sport-racer",
                ),
            ),
            Style(
                "sightseeing",
                "Sightseeing",
                "📸",
                "Comfortable all day",
                ("maxi-skirt", "a-line-dress", "tee-trousers-flats"),
            ),
        ),
    ),
    # "Campus", not "school": clothes for a day of classes, and deliberately nothing short,
    # sheer or underwear-as-outerwear in it. A test holds it to that.
    Occasion(
        "campus",
        "Campus",
        "🎓",
        "What's the day like?",
        (
            Style(
                "campus-casual",
                "Casual",
                "🎒",
                "Easy layers",
                ("tee-jeans", "cardigan-jeans", "leggings-cardigan"),
            ),
            Style(
                "preppy",
                "Preppy",
                "📚",
                "Blouses and cardigans",
                ("preppy-a-line", "preppy-cardigan", "shirt-dress"),
            ),
            Style("sporty", "Sporty", "⚽", "Tee and leggings", ("gym-tee-leggings", "tee-trousers-flats")),
        ),
    ),
    Occasion(
        "private",
        "Private",
        "🔒",
        "Just for the two of you?",
        (
            Style(
                "anime-beachwear",
                "Anime Beachwear",
                "🏖️",
                "Twelve adult anime-inspired bikinis and swimsuits for beach and pool",
                (
                    "beach-ocean-stripe",
                    "beach-sakura-ties",
                    "beach-midnight-string",
                    "beach-violet-halter",
                    "beach-sunset-bandeau",
                    "beach-pearl-bandeau",
                    "beach-scarlet-scoop",
                    "beach-indigo-highcut",
                    "beach-noir-cutout",
                    "beach-rose-ruffle",
                    "beach-aqua-skirt",
                    "beach-sport-racer",
                ),
            ),
            Style(
                "fan-service",
                "Fan service",
                "✨",
                "Teasing, playful",
                ("corset-mini", "visible-thong-jeans", "fishnets-mini"),
                content=_profile("waist", ("waistline", "lower-back"),
                                 ("neotribal-heart-01", "heart-stars-01")),
            ),
            # CR1. The Y2K whale tail: a V-string's straps and back above low-rise jeans.
            Style(
                "y2k-reveal",
                "Y2K reveal",
                "🦋",
                "Visible straps over low-rise denim",
                ("visible-v-string-y2k", "visible-thong-jeans"),
                content=_profile("waist", ("waistline", "lower-back"),
                                 ("tribal-butterfly-01", "neotribal-heart-01", "waist-filigree-01")),
            ),
            # The style ids "lingerie" and "glamour" are kept from OC1: looks already in her
            # wardrobe are tagged with them.
            Style(
                "lingerie",
                "Lace editorial",
                "🖤",
                "Lace and satin sets",
                (
                    "italian-lace-thong",
                    "italian-lace-brazilian",
                    "lace-lingerie-set",
                    "balconette-set",
                    "plunge-thong",
                ),
                content=_profile("back", ("waistline", "lower-back", "upper-back"),
                                 ("rose-vine-01", "ornamental-butterfly-01", "lotus-ornament-01")),
            ),
            Style(
                "corsetry",
                "Corsetry",
                "🎀",
                "Guêpière, bodysuit, corset",
                ("guepiere", "bodysuit", "corset-mini"),
                content=_profile("construction", ("upper-back", "spine-upper", "nape"),
                                 ("lace-ornament-01", "spine-vine-01")),
            ),
            Style(
                "glamour",
                "Stockings & suspenders",
                "💋",
                "Stockings, belts and straps",
                ("stockings-mini-dress", "stockings-pencil", "stockings-discreet", "fishnets-mini"),
                content=_profile("legs", ("upper-back", "lower-back", "nape"),
                                 ("lace-ornament-01", "rose-vine-01")),
            ),
            Style(
                "sheer-layering",
                "Sheer layering",
                "🫧",
                "See-through over a mini",
                ("sheer-blouse", "sheer-blouse-bralette"),
                content=_profile("construction", ("nape", "upper-back"),
                                 ("nape-crescent-01", "lace-ornament-01")),
            ),
            # CR1. Looks measured to leave her waistline and lower back bare. It never applies a
            # tattoo: it offers the looks, and the body art the finished look's exposure allows.
            Style(
                "body-art-focus",
                "Body-art focus",
                "🦋",
                "Looks that show the lower back",
                (
                    "italian-lace-brazilian",
                    "lace-lingerie-set",
                    "visible-v-string-y2k",
                    "plunge-thong",
                    "club-waistline",
                    "y2k-low-rise",
                ),
                content=_profile("waist", ("waistline", "lower-back", "upper-back"),
                                 ("tribal-butterfly-01", "waist-filigree-01", "rose-vine-01",
                                  "neotribal-heart-01")),
            ),
        ),
        private=True,
    ),
)


def occasions() -> dict[str, Occasion]:
    return {occasion.id: occasion for occasion in OCCASIONS}


def tag(value: dict | None) -> tuple[str | None, str | None]:
    """``options.occasion`` checked against the catalogue: (occasion, style), or Nones.

    A style that is not in the named occasion is dropped and the occasion kept; an unknown
    occasion drops both. Never raises: a label is not worth failing a fitted look over.
    """
    if not isinstance(value, dict):
        return None, None
    occasion = occasions().get(str(value.get("occasion") or ""))
    if occasion is None:
        return None, None
    style = str(value.get("style") or "")
    return occasion.id, style if any(s.id == style for s in occasion.styles) else None


def catalogue(entries: dict[str, dict]) -> list[dict]:
    """The occasions as ``GET /v1/outfits`` lists them, beside the dictionary's planned ``entries``.

    Each style says what its looks are rated so a client can hide it without fetching
    anything else: ``general`` (all general), ``private`` (all private) or ``mixed``.
    """
    out = []
    for occasion in OCCASIONS:
        styles = []
        for style in occasion.styles:
            ratings = {entries[look]["rating"] for look in style.looks}
            styles.append(
                {
                    "id": style.id,
                    "title": style.title,
                    "icon": style.icon,
                    "blurb": style.blurb,
                    "looks": list(style.looks),
                    "rating": ratings.pop() if len(ratings) == 1 else "mixed",
                    **({"collection": style.collection} if style.collection else {}),
                    **({"content": style.content.to_dict()} if style.content else {}),
                }
            )
        out.append(
            {
                "id": occasion.id,
                "title": occasion.title,
                "icon": occasion.icon,
                "question": occasion.question,
                "private": occasion.private,
                "styles": styles,
            }
        )
    return out


def planned(catalog: TemplateCatalog) -> list[dict]:
    """The catalogue against the dictionary as this Forge's planner makes it."""
    from wardrobe.pipeline.outfit_dictionary import catalogue as outfits

    return catalogue({entry["id"]: entry for entry in outfits(catalog)["outfits"]})


__all__ = [
    "BODY_ART_MOODS",
    "DETAILS",
    "OCCASIONS",
    "SHOTS",
    "ContentProfile",
    "Occasion",
    "Style",
    "catalogue",
    "occasions",
    "planned",
    "tag",
]
