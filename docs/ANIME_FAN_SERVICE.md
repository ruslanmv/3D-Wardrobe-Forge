# Anime Fan Service — the collection

> Status: **AN0–AN2 built.** Twelve looks, four sections, one occasion. The
> garments, palettes, prints and cuts are built and fitted by the real pipeline.
> Accessories (headpieces, wings, gloves, sashes, braces, jewellery) are designed
> below and not built yet (AN4).
>
> Batches are `AN0`–`AN4`. Commit subjects and code comments carry the prefix.

Twelve costumes in the spirit of well-known adult anime heroines, made for an app
in which a person dresses a companion avatar for fun. They are **original designs**.
Each look takes a heroine's silhouette and palette: a striped bikini under low-rise
jeans, a floral gown slit to the thigh, a latex catsuit and over-the-knee boots.
Each is named by the collection, never by a character. No character name, emblem,
logo, tattoo or artwork is used or shipped.

The record of what inspired each look is
[`assets/anime/fan_service_collection.json`](../assets/anime/fan_service_collection.json)
(`inspiredBy`). It is a design note for whoever extends the collection. It is not
served, not shown and it grants nothing.

## The four sections

The collection is an occasion of its own, **Anime fan service**, with one style per
section. In the Studio it is a first-screen occasion like Night out or Vacation.

### Beach & pool (`anime-beach`)

| Look | Built from | Rating | Inspired by |
| --- | --- | --- | --- |
| **Ocean Navigator** | green-and-white striped triangle bikini (top and bottoms as a set), low-rise blue jeans | private | Nami, *One Piece* |
| **Island Archaeologist** | purple cropped cami, pink-and-white **floral** wrap sarong **slit** up the left leg | general | Nico Robin, *One Piece* |

Both also appear as **Anime beach** under Vacation. The sarong look is for everyone.
The bikini shows only with private mode on.

### Retro & catsuits (`anime-retro`)

| Look | Built from | Rating | Inspired by |
| --- | --- | --- | --- |
| **Retro Bounty Hunter** | yellow halter crop top, yellow denim shorts, red cropped jacket **worn open**, white over-the-knee boots | general | Faye Valentine, *Cowboy Bebop* |
| **Midnight Thief** | black latex catsuit plunging to the sternum, black over-the-knee boots | general | Fujiko Mine, *Lupin III* |

### Glamour & fantasy (`anime-glamour`)

| Look | Built from | Rating | Inspired by |
| --- | --- | --- | --- |
| **Thorn Assassin** | black satin halter gown **slit** up the left thigh, black thigh-high stockings, black stiletto ankle boots | general | Yor Forger, *Spy × Family* |
| **Serpent Empress** | red satin halter gown in a pink **floral** print, **slit** up the left thigh, red stiletto ankle boots | general | Boa Hancock, *One Piece* |
| **Abyss Guardian** | white satin halter gown **slit** up the left thigh, black stiletto ankle boots | general | Albedo, *Overlord* |
| **Reaper Lieutenant** | black long-sleeved wrap robe with a plunging neckline, black wide trousers | general | Rangiku Matsumoto, *Bleach* |

### Action heroines (`anime-action`)

| Look | Built from | Rating | Inspired by |
| --- | --- | --- | --- |
| **Rose Commander** | pink latex catsuit plunging to the sternum, pink over-the-knee boots | general | Vinsmoke Reiju, *One Piece* |
| **Moon Rabbit Hero** | white high-cut one-piece worn as a leotard, white over-the-knee boots | private | Mirko, *My Hero Academia* |
| **Ice General** | white tailored blazer, white mini pencil skirt, black over-the-knee stiletto boots | general | Esdeath, *Akame ga Kill!* |
| **Ghost Operative** | black high-cut bodysuit, black thigh-high stockings, black cropped jacket **worn open**, black combat boots | private | Motoko Kusanagi, *Ghost in the Shell* |

## Who sees what

- **The occasion is private as a whole** (`Occasion.private`). Without private
  mode the Studio does not show it, not even as a locked tile, exactly as it treats
  Private.
- **Ratings are Forge's, not the collection's.** Each look is an outfit-dictionary
  entry, and its rating is computed from the planner. A look is `private` when any
  garment needs the adult declaration. Here that means the bikini, the swimsuit worn
  as a leotard and the bodysuit. The dictionary has two groups, `anime` and
  `anime-private`, because a group's private flag is checked against the computed
  rating in both directions (`tests/unit/test_outfit_dictionary.py`).
- **The server gate runs on every job**, as it does for any look. A private look
  on an avatar nobody declared adult is refused. A VRM whose own terms disallow
  sexual use is refused whatever the declaration. Nothing in the collection grants
  or skips anything.
- **Adult characters, adult avatars.** Every heroine the collection draws on is an
  adult in her series (`adultCharacter: true` in the record). The README pictures
  are made on VRoid Female with the operator's adult declaration for that run, as
  every gated sheet is (`tools/gallery/real_avatar.py`). An avatar presented as a
  minor is never dressed in these looks.

## What the collection needed, and got (AN1)

Four of the twelve could not be made with the vocabulary the planner had. The new
words are general, not anime-specific. Any prompt can use them.

| Need | Words | Where |
| --- | --- | --- |
| A gown or skirt slit up one leg | "thigh slit", "high slit", "side slit", "slit" | `StylePlan.slit`, `procedural.slit_profile` |
| A jacket worn open over the top under it | "worn open", "open front", "unbuttoned", "bolero" | `StylePlan.front`, `procedural.open_front_profile` |
| A resort print | "floral", "flower print", "hibiscus", "blossom print" | pattern `floral`, `textures._floral` |

- **Slit.** Every skirt is lofted from horizontal rings, so a slit is cut the way
  a neckline is (`trim`): the hem rises in a notch over the front of her left
  thigh, to 70% of the way from her knee to her hip. The notch is widest at the
  hem and closes to a point. It stays a cut, not a new mesh: the vertex count is
  unchanged. A hem already within 10 cm of the slit's top (a mini) gets nothing.
- **Open front.** The cropped jacket's band is cut in a V from the collar to the
  hem at her front centre, so the top underneath shows (the yellow halter under
  the red jacket).
- **Floral.** A two-colour tile like stripes and gingham, coloured rather than
  tinted. Five-petal blossoms in the second colour, their hearts the ground lifted
  toward white, leaves the ground darkened. "Red and pink floral" is red with pink
  flowers. Generated and Apache-2.0, like every pattern here.
- **Absent unless asked for.** None of the three fields enters a garment's id or
  metadata unless set (`providers/templates.py`). Every garment made before AN1
  keeps its id and its geometry.

Two fixes the collection exposed, both general:

- **Her skin under a revealing cut.** A plunging catsuit on VRoid Female opened
  onto the black top painted on her chest: VRoid exports paint or cut away the
  skin under the outfit. Skin restoration (SR1) ran only for underwear and
  swimwear. It now also runs when an outer garment is cut to show skin her
  clothes hid: a V, plunge or sweetheart neckline, an open back, or a slit
  (`prepare_base_body.reveals_hidden_skin`). An ordinary outfit still never
  touches her skin.
- **Boots go under what hangs over them.** A boot was cut round every layer
  already fitted, so ankle boots under a floor-length gown were cut round the
  gown's hem: a drum 30 cm across at her ankles. Over-the-knee boots under a
  pencil skirt took the skirt's width all the way down. Boots are now cut round
  her legs and the layers that hug them (stockings, trousers, a catsuit), never a
  dress, skirt, jacket or nightgown (`engines.shell._leg_layers`).

## Accessories (AN4, designed, not built)

What each look still lacks is in its record's `deferred` list. It is almost all
one kind of thing: a **rigid accessory bound to one bone**. A garment shell is
fitted round her body. An accessory is not fitted; it is placed. So it is its own
small builder, not a new garment shell.

| Kind | Looks | Bone | Notes |
| --- | --- | --- | --- |
| Headpiece: rabbit ears, horns, a rose ornament, a peaked cap | Moon Rabbit, Abyss Guardian, Thorn Assassin, Ice General | head | Placed on the skull above her hair. Hair is measured, never cut. |
| Wings | Abyss Guardian | upper chest, behind | Two feathered planes, alpha-tested. Spring bones later, with the platform's. |
| Gloves (opera, fingerless) | Thorn Assassin, Rose Commander, Moon Rabbit, Abyss Guardian | lower arm, hand | A sleeve tube from the wrist to above the elbow (`build_sleeves` already fits the arm). The hand is the hard part. |
| Sash, belt, braces | Serpent Empress, Reaper Lieutenant, Midnight Thief, Ice General, Retro Bounty Hunter | hips / chest | Flat ribbons laid on the fitted garment: the hosiery strap code (`suspender_straps`) already lays a ribbon on a surface. |
| Cape | Rose Commander, Serpent Empress | upper chest | A draped panel from the shoulders. Needs the skirt drape the hosiery previews use. |
| Jewellery, sunglasses | Ocean Navigator, Serpent Empress, Island Archaeologist | wrist / ear / head | Small rigid meshes, `metallic` finish. |

The order: gloves and the ribbon family first, because they reuse fitted code;
headpieces next; wings and capes last.

## Rights

- These are original designs. A silhouette and a colour scheme are a style, and a
  style is what the collection takes. It does not take any character's name,
  emblem, logo, tattoo or artwork.
- Titles in the Studio, the dictionary and any pack are the collection's own.
  `tests/unit/test_anime_fan_service.py` fails if a title, prompt or id names a
  character or a series from the record.
- Review franchise rights before any commercial use of these designs. Selling a
  look described as a named character's costume is a different act from offering
  "Serpent Empress", and the repository does neither.
- The avatar's own licence still decides whether it may be modified at all
  (`licensing.evaluate`, every job).

## Tests

`tests/unit/test_anime_fan_service.py`:

- twelve looks, each in the dictionary and in exactly one section;
- no title, prompt or id names a character or a series;
- the computed ratings (three private, nine general);
- the beach style on Vacation is never empty without private mode;
- the slit and open-front words parse, and are absent when not asked for;
- the slit's geometry: high on her left thigh only, the vertex count unchanged, and
  no slit on a mini;
- the open front;
- the floral print's two colours.
