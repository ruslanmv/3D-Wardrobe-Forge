# Adult atelier

Batch `AA`. The order book is `wardrobe/atelier/orders.py`. It is also
`GET /v1/outfits` → `atelier`, which a client may ignore.

## What was missing

The haul analysis sorted her looks and the catalogue. Two different gaps got
called "missing clothes":

1. **Looks the dictionary already names.** Red bodycon, the slip, the skater,
   the four nightclub dresses, the stocking looks, the balconette, the plunge
   thong, the lace bodysuit, the two Italian lace sets. Forge plans every one
   of them. They are not on her because nobody has run the job. The book lists
   them as `queued`. No new geometry.
2. **Cuts the catalogue did not list as cards.** A plunge, a backless mini, a
   thigh slit, a fishnet bodystocking, a babydoll, a short robe, a micro
   bikini, a high-leg swimsuit, a cut-out monokini, pumps, platform heels.
   Most of these were already *words*: "plunge" recut a neckline, "micro"
   scaled a bikini, "vinyl" selected the latex finish, "bustier" selected the
   corset. None of them was a card in ＋ Altro, so picking a colour on a card
   could not own the cut.

   Six cards were built and then removed. On Model Girl the micro mini, the
   vinyl mini, the leather mini, the booty shorts, the mesh top and the
   bralette top left her turquoise dress on. They are not in the catalogue.
   "Hot pants" is the denim short again. "Bralette" is the lingerie bralette.

A third list needs a shape that does not exist. Those rows are `shape`. They
have no template. Asking for strappy sandals still returns the flats, and the
book says so.

## How a card owns its cut

A template's `fit` may now carry `slit`, `finish`, `pattern` and `opacity`,
the same way it already carried neckline, back, coverage and straps. The
prompt wins when it names one. When it does not — the catalogue sends the
card and a colour — the card's own value is used. Empty still means what it
meant: no slit, matte, no pattern, opaque.

Every new card is `optIn`. Its tags are phrases the old prompts do not
contain, so "micro bikini" is still a coverage on the triangle set, "backless
dress" is still the A-line, "hot pants" is still the denim short, and
"stiletto boots" is still the ankle boot. "Stiletto
pumps" is the pump. "Sheer mini dress" stays the skater the gallery already
built; the sheer card answers to "mesh mini dress", and a colour picked on
the card keeps it sheer.

The shell is one that already builds:

| Card | Shell | What the card adds |
| --- | --- | --- |
| Plunge mini, backless mini, sheer mini | `dress` | neckline, back, opacity 0.55 |
| Thigh-slit gown | `dress`, floor length, hips not shins | `slit: high` |
| Fishnet bodystocking | `catsuit` | pattern fishnet. Its sleeves clear the arm; other fishnet is unchanged |
| Babydoll | `slip-dress` | mini, opacity 0.55 |
| Short robe | `open-cardigan` | mini, satin. What she wears comes off first, then the robe. "kimono" selects it |
| Micro bikini | `bikini` | coverage micro, triangle, string |
| High-leg swimsuit | `bodysuit-block` | french-cut leg |
| Cut-out monokini | `bodysuit-block` | waist-side windows |
| Stiletto pumps, platform heels | `boots` | shaft `pump` (ends at the ankle). The 40 mm platform is the stance. A shin with no foot gets a last, so the needle is in the mesh |

See-through cards set `requiresAdult`, so the public catalogue does not list
them. Swimwear was already gated by its category. A slit gown and a pump are
not see-through and are not gated: the same rule as the leather dress and the
stiletto boot that already shipped. Vinyl is the latex finish, which is
opaque.

Each built row is also a dictionary look, in the group its rating requires.
`atelier` is private. The general cards sit in Dressy, Cozy or Swim.

## What is not a card

| Row | Why there is no template |
| --- | --- |
| Cut-out dress | Windows exist on the bodysuit block, not on a dress. The monokini uses them |
| Bandage dress | Horizontal bands are not a tighter bodycon |
| Lace-up top | No lace-up opening |
| Strappy sandals | A pump is closed. Today the words still plan the flats |
| Choker, opera gloves, body chain | No accessory category |
| Harness on its own | Harness is a strap network on a garment, not a garment |
| Maid, bunny | No apron, ears, cuffs or tail. Nurse and police are already looks made of clothes that exist |
| Kimono collar | The word selects the short robe. The overlapping collar is not built |
| Bustier, teddy | Already the corset and the tailored bodysuit |
| Latex as a material | Already a finish. "latex", "vinyl" and "pvc" all select it |

## Cloth

A dress and a skirt compile to a cloth asset (`wardrobe/cloth`), as they did.
The pump is rigid, like every boot. The atelier does not invent seams.

## Adding the next one

1. If a shell can cut it, add an opt-in template whose tags are phrases no
   current prompt contains, set the cut on `fit`, and add a `built` row in
   `wardrobe/atelier/orders.py`. The dictionary look is generated from that row.
2. If the word already selects a template, add an `already` row. Do not add a
   second card.
3. If it needs a new shape, add a `shape` row and do not add a template.
4. `pytest tests/unit/test_atelier.py tests/unit/test_outfit_dictionary.py
   tests/unit/test_templates.py tests/unit/test_palettes.py`
