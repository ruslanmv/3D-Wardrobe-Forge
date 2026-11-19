# ES1–ES3 — Erotic sets dressed over her bare body, and partial undress

## ES1. `baseBody: "bare-dressed"`

A job may now dress her **over her prepared bare body**, instead of over her
source skin. The bare preparation is the same one (`bare_body.prepare`):

- the five bare gates
- the detail clearance when `bareDetail` is asked (and `bareState` with it)
- skin restoration and the band check

Then the outfit is planned, built and fitted as usual.

- **Why.** Whatever comes off later shows her own skin, and its detail if
  painted. It does not show clothing painted on her texture.
- **Guards.** Every guard that treated bare as private and uncached asks
  `JobOptions.over_bare_body`: the jobs, generate and catalog routes, the
  studio's admin-only rule, the orchestrator's cache bypass, and prebuilt. Only
  `base_body_mode == "bare"` skips garment generation.
- **Tag.** The look carries `extras.wardrobeForge.overBare: true` (with `detail`
  and `state` when painted), never `bare: true`. Its `wardrobeState` is
  `"over-bare"`, so a client that reads "bare" as "nothing on" does not mistake
  it.
- **Refused:** no outfit, body art, a body surface, or `ensureFoundation` (the
  bare preparation is her foundation).

## ES2. Partial undress: `hideBySlot`

`/v1/visibility` answers with the same materials it hides in `hideMaterials`,
grouped by slot (`tops`, `bottoms`, `onepiece`, `shoes`, `other`). A client can
hide only the bottom (bottomless, top kept) or only the top, live and
reversibly, with no new file. It is the same gate as before: an empty `{}`
whenever anything refuses.

## ES3. The erotic group

The new outfit-dictionary group is `erotic` ("Erotic sets · adults", private).
Every entry carries `options: {"baseBody": "bare-dressed"}` and `partial`, the
halves that can come off alone:

| id                    | set                                                   | activities                 | partial     |
| --------------------- | ----------------------------------------------------- | -------------------------- | ----------- |
| `erotic-boudoir`      | lace balconette, garter set, thigh-highs               | boudoir, striptease, bedroom | top, bottom |
| `erotic-seduction`    | sheer babydoll, thong                                  | seduction, bedroom         | top, bottom |
| `erotic-dominant`     | leather corset, leather garter, g-string, over-knee boots | dominant, role-play      | top, bottom |
| `erotic-fishnet`      | fishnet bodystocking, stilettos                        | club, tease                | —           |
| `erotic-cutout`       | cut-out bodysuit, stilettos                            | date night, tease          | —           |
| `erotic-massage`      | bralette, thong                                        | massage, slow, bedroom     | top, bottom |
| `erotic-after-shower` | short robe, thong                                      | shower, morning            | bottom      |
| `erotic-guepiere`     | guêpière, g-string, thigh-highs                        | striptease, boudoir        | top, bottom |
| `erotic-micro-bikini` | micro bikini                                           | pool, sun, tease           | top, bottom |
| `erotic-night-out`    | sheer bodycon mini, thong, stilettos                   | night out, tease           | bottom      |

`tools/prebuild.py --outfits` sends each set with its own options (and without
`ensureFoundation`), only to characters declared adult. The bare gates refuse
any character without a clearance.

**Not yet:**

- The satin chemise can't be reached by prompt: the planner sends "chemise" to
  nightwear's default nightgown.
- Open-cup and crotchless pieces need new procedural builders.
- The companion app's partial-undress requests ("take off your bottom") are the
  client's step.

Tests: `tests/unit/test_erotic_sets.py`, `tests/integration/test_bare_body.py`
(`-k dressed_over_bare`), and `tests/unit/test_clothing_visibility.py`
(`hideBySlot`).

## Outfits for the shows (VA4)

The chatbot's Private shows (`src/experiences/private/PrivateRoutines.js`) have
looks made for them, in the same private Erotic group and dressed over her bare
body (`baseBody: bare-dressed`), so the admin panel offers them.

**Striptease: five pairs.** A striptease takes three layers off, one look down
at a time through her own looks. Each set is the outfit plus the matching
lingerie under it: dressed, then the lingerie, then its top alone (`partial`),
then bare. Generate both looks of a pair for her.

| Dressed                                            | Underneath                                           |
| -------------------------------------------------- | ---------------------------------------------------- |
| `show-strip-red`: red slip dress                   | `show-strip-red-under`: red lace balconette & thong  |
| `show-strip-office`: white blouse & pencil skirt   | `show-strip-office-under`: black lace & stockings    |
| `show-strip-trench`: trench coat & lingerie        | `show-strip-trench-under`: lace set & stockings      |
| `show-strip-lbd`: little black dress               | `show-strip-lbd-under`: black bra & thong            |
| `show-strip-robe`: short robe & garters            | `show-strip-robe-under`: balconette & garters        |

**Table dance: five looks.** `show-table-sequin` (sequin mini and fishnets),
`show-table-shorts` (denim shorts and bralette), `show-table-lace-body` (red lace
bodysuit), `show-table-sheer-crop` (sheer crop and thong) and
`show-table-pink-bikini` (pink micro bikini).

Every garment is a real template (`tests/unit/test_erotic_sets.py` checks each
look, and that the underneath look is exactly the dressed one's underwear,
legwear and shoes). All fifteen were built end to end on Forge's synthetic adult
reference body.
