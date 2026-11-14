"""AA. The order book: one row per missing adult garment from the haul analysis.

Four statuses, and a row never changes status by being described well:

- ``built`` — a new opt-in card. The shell already existed; the card owns the
  cut (neckline, back, slit, coverage, finish, pattern, opacity) so picking it
  with only a colour still builds that garment.
- ``queued`` — already a dictionary look. Forge can make it. Nothing here adds
  a shape; the look still has to be made for her.
- ``already`` — the word already selects a card (a bustier is the corset).
- ``shape`` — the catalogue has no shell for it. No card pretends otherwise.

``GET /v1/outfits`` carries ``atelier`` as this book. It grants nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Templates in the catalogue before these cards. The palette test keeps the sum honest.
CATALOG_BEFORE_ATELIER = 105


@dataclass(frozen=True)
class Order:
    id: str
    title: str
    status: str
    prompt: str = ""
    group: str = ""
    template_id: str | None = None
    outfit_id: str | None = None
    why: str = ""
    band: str = ""
    #: (plan path, value) the card must keep when the prompt is only a colour.
    baked: tuple[tuple[str, object], ...] = ()
    tags: tuple[str, ...] = ()
    #: The template's requiresAdult flag. Swimwear is gated by its category instead.
    adult_card: bool = False


def _built(
    id_: str, title: str, prompt: str, group: str, template_id: str, band: str,
    baked: tuple[tuple[str, object], ...] = (), *, adult: bool = False,
    tags: tuple[str, ...] = (),
) -> Order:
    return Order(
        id_, title, "built", prompt, group, template_id, why="", band=band, baked=baked,
        tags=tags or ("atelier",), adult_card=adult,
    )


ORDERS: tuple[Order, ...] = (
    # --- cards (the shell existed; the cut did not have a name of its own) ---
    _built(
        "aa-plunge-mini", "Plunge mini", "black plunge neckline dress", "dressy",
        "dress-plunge-mini-v1", "complete",
        (("style.neckline", "plunge"), ("hem", "mini"), ("silhouette", "sheath")),
    ),
    _built(
        "aa-backless-mini", "Backless mini", "black backless mini dress", "dressy",
        "dress-backless-mini-v1", "complete",
        (("style.back", "low"), ("hem", "mini")),
    ),
    _built(
        "aa-slit-gown", "Thigh-slit gown", "black thigh slit gown", "dressy",
        "dress-slit-gown-v1", "complete",
        (("style.slit", "high"), ("hem", "floor")),
    ),
    _built(
        "aa-sheer-mini", "Sheer mini", "black sheer mini dress", "atelier",
        "dress-sheer-mini-v1", "complete",
        (("material.opacity", 0.55), ("hem", "mini")),
        adult=True, tags=("atelier", "sheer"),
    ),
    _built(
        "aa-micro-mini", "Micro mini", "black micro mini skirt", "dressy",
        "skirt-micro-mini-v1", "complete",
        (("style.coverage", "micro"), ("hem", "mini")),
    ),
    _built(
        "aa-vinyl-mini", "Vinyl mini", "black vinyl mini skirt", "dressy",
        "skirt-vinyl-mini-v1", "complete",
        (("material.finish", "latex"), ("hem", "mini")),
    ),
    _built(
        "aa-leather-mini", "Leather mini", "black leather mini skirt", "dressy",
        "skirt-leather-mini-v1", "complete",
        (("material.finish", "satin"), ("hem", "mini")),
    ),
    _built(
        "aa-booty-shorts", "Booty shorts", "black hot pants", "dressy",
        "shorts-booty-v1", "complete",
        (("style.coverage", "micro"),),
    ),
    _built(
        "aa-mesh-top", "Mesh top", "black mesh top", "atelier",
        "top-mesh-v1", "lingerie",
        (("material.opacity", 0.55),),
        adult=True, tags=("atelier", "sheer"),
    ),
    _built(
        "aa-bralette-top", "Bralette top", "black bralette top", "atelier",
        "top-bralette-outer-v1", "lingerie",
        tags=("atelier", "bralette"), adult=True,
    ),
    _built(
        "aa-bodystocking", "Fishnet bodystocking", "black bodystocking", "atelier",
        "jumpsuit-bodystocking-v1", "lingerie",
        (("material.pattern", "fishnet"),),
        adult=True, tags=("atelier", "fishnet"),
    ),
    _built(
        "aa-babydoll", "Babydoll", "black babydoll", "atelier",
        "night-babydoll-v1", "lingerie",
        (("material.opacity", 0.55), ("hem", "mini")),
        adult=True, tags=("atelier", "sheer"),
    ),
    _built(
        "aa-short-robe", "Short robe", "black short robe", "cozy",
        "night-short-robe-v1", "home",
        (("material.finish", "satin"), ("hem", "mini")),
        tags=("atelier", "robe"),
    ),
    _built(
        "aa-micro-bikini", "Micro bikini", "black micro bikini set", "swim",
        "swim-micro-bikini-v1", "swim",
        (("style.coverage", "micro"), ("style.neckline", "triangle"), ("style.straps", "string")),
        tags=("atelier", "swim"),
    ),
    _built(
        "aa-high-leg", "High-leg swimsuit", "black high-leg swimsuit", "swim",
        "swim-high-leg-v1", "swim",
        (("style.leg_cut", "high"),),
        tags=("atelier", "swim"),
    ),
    _built(
        "aa-monokini", "Cut-out monokini", "black cut-out monokini", "swim",
        "swim-cutout-monokini-v1", "swim",
        tags=("atelier", "swim"),
    ),
    _built(
        "aa-pumps", "Stiletto pumps", "black stiletto pumps", "dressy",
        "shoes-stiletto-pumps-v1", "shoes",
        tags=("atelier", "shoes"),
    ),
    _built(
        "aa-platform-heels", "Platform heels", "black platform heels", "dressy",
        "shoes-platform-heels-v1", "shoes",
        tags=("atelier", "shoes"),
    ),
    # --- queued: written, plannable, not yet made for her ---
    Order("red-bodycon", "Red bodycon mini", "queued", outfit_id="red-bodycon",
          why="Dictionary look. No new card.", band="complete"),
    Order("slip-dress", "Satin slip dress", "queued", outfit_id="slip-dress",
          why="Dictionary look. No new card.", band="complete"),
    Order("skater-dress", "Skater mini dress", "queued", outfit_id="skater-dress",
          why="Dictionary look. No new card.", band="complete"),
    Order("discoteca-stiletto-ankle", "Black dress & stiletto ankle boots", "queued",
          outfit_id="discoteca-stiletto-ankle", why="One of the four nightclub dresses.", band="complete"),
    Order("discoteca-platform", "Black dress & platform boots", "queued",
          outfit_id="discoteca-platform", why="One of the four nightclub dresses.", band="complete"),
    Order("discoteca-combat", "Black dress & combat boots", "queued",
          outfit_id="discoteca-combat", why="One of the four nightclub dresses.", band="complete"),
    Order("discoteca-over-knee", "Black dress & over-the-knee boots", "queued",
          outfit_id="discoteca-over-knee", why="One of the four nightclub dresses.", band="complete"),
    Order("stockings-mini-dress", "Mini dress & stockings", "queued",
          outfit_id="stockings-mini-dress", why="Dictionary look. The preset carries the stockings.",
          band="complete"),
    Order("fishnets-mini", "Mini skirt & fishnets", "queued", outfit_id="fishnets-mini",
          why="Dictionary look.", band="complete"),
    Order("sheer-blouse", "Sheer blouse & mini", "queued", outfit_id="sheer-blouse",
          why="Dictionary look.", band="complete"),
    Order("stockings-pencil", "Pencil skirt & seamed stockings", "queued",
          outfit_id="stockings-pencil", why="Dictionary look.", band="complete"),
    Order("balconette-set", "Balconette set", "queued", outfit_id="balconette-set",
          why="Dictionary look.", band="lingerie"),
    Order("plunge-thong", "Plunge bra & thong", "queued", outfit_id="plunge-thong",
          why="Dictionary look.", band="lingerie"),
    Order("bodysuit", "Lace bodysuit", "queued", outfit_id="bodysuit",
          why="Dictionary look.", band="lingerie"),
    Order("italian-lace-thong", "Italian lace set · thong", "queued",
          outfit_id="italian-lace-thong", why="Dictionary look.", band="lingerie"),
    Order("italian-lace-brazilian", "Italian lace set · Brazilian", "queued",
          outfit_id="italian-lace-brazilian", why="Dictionary look.", band="lingerie"),
    # --- already a card, under another name ---
    Order("bustier", "Bustier", "already", prompt="black bustier", template_id="top-corset-v1",
          why="The word bustier selects the corset top."),
    Order("teddy", "Teddy", "already", prompt="black teddy", template_id="under-bodysuit-v2",
          why="The tailored bodysuit is tagged teddy."),
    Order("latex-catsuit", "Latex catsuit", "already", prompt="black latex catsuit",
          template_id="jumpsuit-catsuit-v1",
          why="Latex is a finish. Vinyl and pvc are the same finish. The catsuit card already takes it."),
    Order("roleplay-nurse", "Nurse", "already", outfit_id="roleplay-nurse",
          why="A white bodycon, sheer stockings and pumps, composed from cards. No cap."),
    Order("roleplay-police", "Police officer", "already", outfit_id="roleplay-police",
          why="A navy tee, pleated mini, stockings and boots. No badge."),
    # --- no shell yet: do not ship a card ---
    Order("cut-out-dress", "Cut-out dress", "shape",
          why="A dress has no windows. The waist-side cut exists only on the bodysuit block, "
               "which the cut-out monokini uses."),
    Order("bandage-dress", "Bandage dress", "shape",
          why="Horizontal bands are not a tighter bodycon. No card is named bandage."),
    Order("lace-up-top", "Lace-up top", "shape",
          why="Nothing builds a lace-up opening."),
    Order("strappy-sandals", "Strappy sandals", "shape",
          why="A pump is a closed shoe. An open toe and straps are not a pump and not a flat."),
    Order("choker", "Choker", "shape", why="No accessory category, and no neck band."),
    Order("opera-gloves", "Opera gloves", "shape", why="No glove, and sleeves are not gloves."),
    Order("body-chain", "Harness or body chain", "shape",
          why="Harness is a strap network on a top, not a garment of its own. No body chain."),
    Order("maid", "Maid", "shape",
          why="No apron, cap or cuffs. Nurse and police are already composed from clothes that exist."),
    Order("bunny", "Bunny", "shape",
          why="No ears, collar, cuffs or tail."),
    Order("kimono-collar", "Kimono collar", "shape",
          why="The word kimono selects the short robe. An overlapping collar is not built."),
)


def built_orders() -> tuple[Order, ...]:
    return tuple(order for order in ORDERS if order.status == "built")


def report() -> dict:
    """The book, grouped, for ``GET /v1/outfits``. No planning: the rows are the book."""
    grouped: dict[str, list[dict]] = {"built": [], "queued": [], "already": [], "shape": []}
    for order in ORDERS:
        row = {
            "id": order.id,
            "title": order.title,
            "status": order.status,
            "band": order.band,
            "why": order.why,
        }
        if order.template_id:
            row["template"] = order.template_id
        if order.outfit_id:
            row["outfit"] = order.outfit_id
        if order.prompt:
            row["prompt"] = order.prompt
        grouped[order.status].append(row)
    return {
        "version": 1,
        "built": grouped["built"],
        "queued": grouped["queued"],
        "already": grouped["already"],
        "unbuilt": grouped["shape"],
    }


__all__ = ["CATALOG_BEFORE_ATELIER", "ORDERS", "Order", "built_orders", "report"]
