# Hosiery and suspender styling: design

**Status: designed, not built.** This document specifies an additive feature. Nothing
in it changes a look the Forge makes today.

## 1. What the brief asks for

The styling brief (Calzedonia and Intimissimi on the *reggicalze*, Bluebella on
matching suspender sets, the VienneMilano and Howcast dressing tutorials) comes to
one idea. The effect comes from **how three layers relate to each other**: the
suspender belt, the stockings, and how much of both the outer garment shows. No
single garment carries it. The brief has five looks:

| # | Look | What makes it work |
| --- | --- | --- |
| 1 | Black lace suspender belt + sheer black stockings + short black skirt | The hem just covers the stocking tops standing, and they show when she sits or moves |
| 2 | Suspender belt + fishnet stockings + mini skirt | Fishnet reads retro. A plain skirt and top keep it the only detail |
| 3 | Matching lace set + belt + sheer stockings under a knee or midi dress | Completely conventional outside, with the set underneath |
| 4 | Vintage: high-waisted belt, seamed stockings, fitted skirt or dress | The back seam, and a wide belt that defines the waist (Bluebella's "waspie") |
| 5 | Guêpière + stockings + skirt | A longline corset with its own suspenders, under clothing that is neither very tight nor very short |

It also has two rules that are really geometry:

- **Hem length sets the reveal.** Midi or knee length hides everything. A mini gives
  an occasional glimpse of the stocking tops. A very short mini shows the tops and
  straps on purpose: lingerie worn as outerwear.
- **How it goes on.** Belt at the waist, stockings pulled to the thighs, clips on the
  stocking tops, and straps adjusted so they hold the stockings "without excessive
  tension".

## 2. What the Forge already has, and what it lacks

Already built:
- **Garter strap network** (`build_garter`): a belt at the waist and four straps.
  Used by `under-garter-set-v1` (briefs with suspenders) and by legwear with
  `straps: garter`.
- **Thigh-high stockings** (`legwear-thigh-highs-v1`): an opaque 3.5 cm top band as
  its own trim section. Sheer levels from *slightly sheer* to *very sheer*, fishnet
  as an alpha mask, and tights.
- **Layered outfits**: foundation, then legwear, then main, then one-piece, then
  outer. Each layer clears the ones inside it.
- **Measured fit**: crotch, legs, armpit and shoulders, from
  [FIT_QUALITY](FIT_QUALITY.md).
- **Pose stress test**, which already has `walk` and `sit` poses (`POSE_TESTS`).
- **Adult gate**: underwear and see-through materials need the model's terms plus an
  operator's declaration.

Missing, and what this design adds:

| Gap | Today | Consequence |
| --- | --- | --- |
| G1 | The garter and the stockings each compute the stocking-top height, `hip_y - thigh * 0.4`, independently | Clips meet the band only by coincidence. Measured legs, or a different stocking length, will separate them |
| G2 | Hem length is a fixed fraction (`mini` 0.34, `knee` 0.62, …) with no idea what is underneath | "Covers them standing, shows them seated" cannot be asked for, or checked |
| G3 | The garter exists only as a strap style on briefs or stockings | No suspender belt as its own garment, no waspie, no guêpière, no high-waisted belt |
| G4 | No seamed stocking, and no lace stocking top | Looks 4 and 1 lack their defining detail |
| G5 | Straps are straight sweeps with no rest length | "Without excessive tension" is unchecked. In `sit`, straps can stretch or cut into the thigh |
| G6 | "Matching" carries colour, pattern and finish between pieces | No record that bra, briefs, belt and stockings are one set, so the Studio cannot swap the set |

## 3. Principles

1. **Additive and non-destructive.** Every new field is optional, and its default
   reproduces today's behaviour byte for byte. A test re-runs the 81 gallery looks
   and fails if any existing look's geometry hash changes. Templates are added,
   never edited in place.
2. **Standard, not a trend pack.** The five looks become ordinary templates, style
   parameters and planner words, as the rest of the library is. No trend JSON.
3. **Reveal is garments, never body.** The reveal control moves only the *outer*
   hem, measured against the *hosiery*. It never lowers underwear coverage and
   never exposes anything the garments underneath do not already show.
4. **The gate is unchanged.** Every new piece is gated by the rules that already
   exist: category `underwear`, and `exposes_body` for sheer and fishnet. A look
   is gated when any of its layers is. The adult declaration still comes only from
   the operator and the model's terms.
5. **Measured, not formula.** Clip points, the stocking band and hem heights are
   read from the fitted layers and the measured body, as the real-avatar fit work
   established.

## 4. Components

### 4.1 The stocking-top contract (fixes G1)

When the legwear layer fits, it **publishes** its top band per leg, into the
pipeline context next to `collision_points`:

```python
@dataclass(frozen=True)
class StockingTop:
    side: str                      # "left" | "right"
    band_y: float                  # height of the band's top edge, rest pose
    ring: np.ndarray               # the band's top ring after fitting, (N, 3)
    clips: dict[str, np.ndarray]   # "front", "back", "outer" (and "inner" for 6 straps)
    joints: dict[str, tuple]       # skin binding at each clip, for posed checks
```

Clip points are taken from the fitted ring at fixed angles round the leg, measured
from her front with the angle convention the UVs already use. So a clip sits on
the band wherever the band ended up after fitting.

Anything that attaches to stockings reads `StockingTop` instead of recomputing a
height. With no stockings in the outfit, there is nothing to read, and the belt is
worn alone.

### 4.2 Suspenders as a connector layer (fixes G1, G3, G5)

The belt and the straps split into two things:

- **The belt** is a foundation garment in its own right: a new kind,
  `suspender-belt`, fitted round her waist like any band.
- **The straps** are a new layer role, `connector`, ranked between legwear and the
  main layer. They are built only when the outfit has both a belt and stockings, and
  they run from belt tabs to `StockingTop.clips`.

```text
foundation (bra, briefs?, belt) ─► legwear (stockings) ─► connector (straps) ─► main ─► outer
                                        │ publishes StockingTop      ▲ reads it
```

Strap geometry: a sweep from the belt tab, down the measured front (or back) of the
thigh, to the clip. It follows the surface the way shoulder straps already follow the
upper-body depth map, and uses the same lift: the strap's own radius plus 1 mm.

**Rest length and tension (G5).** Each strap gets a rest length of the path length
plus a slack of 1.5%. The pose stress test skins the straps in `walk` and `sit` and
measures each strap's elongation:

| Elongation in a pose | Result |
| --- | --- |
| ≤ 4% | fine |
| 4–10% | the fit report warns that this strap pulls in `sit`, and the planner lengthens its tab drop once and re-checks |
| > 10% after that | `FittingError`: the garment would not stay on in that pose |

This is the tutorial's "held without excessive tension", made measurable.

**Dressing order.** A traditional set puts the briefs *over* the suspender straps,
so they can come off without unclipping. A new optional style field sets which way:
`briefsOver: true | false`, default `false`, which is today's behaviour. With
`true`, the briefs are fitted after the connector and clear it through the same
collision path layers already use.

### 4.3 Reveal: hem length against the hosiery (fixes G2)

A new optional style field on the outer skirt or dress:

```text
reveal: "discreet" | "glimpse" | "statement"      (absent = today's hem logic, unchanged)
```

When `reveal` is set, and the outfit has stockings with a top band, the planner
**solves** for the hem height instead of reading it from the hem fraction table:

| `reveal` | Standing | Walking | Sitting | The brief's rule |
| --- | --- | --- | --- | --- |
| `discreet` | covered | covered | covered | "midi or knee length: completely hidden" |
| `glimpse` | covered | covered | band shows | "mini: occasional glimpse of stocking tops" |
| `statement` | band and clips show | show | show | "very short mini: intentionally visible, lingerie as outerwear" |

"Covered" is geometry, not pixels. The hem ring and the stocking band are skinned
into each of the existing `POSE_TESTS` poses with the weights the pipeline already
computes. In each pose the check measures the gap, down her front and sides,
between the lowest hem vertex and the highest band or clip vertex. The hem is set
to the highest height that satisfies the row, with a 1.5 cm margin.

- **An explicit length wins.** If the prompt says *mini* and asks for `discreet`,
  and a mini cannot cover the band seated, the explicit length is kept. The fit
  report then says which reveal level the look actually has and why. A user's word
  is never overridden silently.
- **What the report says:**
  `reveal: requested glimpse, achieved glimpse (band visible in: sit)`.

Words the planner learns: *discreet, hidden, subtle* → `discreet`; *peek, glimpse,
flirty* → `glimpse`; *visible garters, on show, lingerie as outerwear* →
`statement`. Italian: *discreto*, *che si intravede*, *a vista*.

### 4.4 Stocking styles (fixes G4)

These are optional template or style fields on legwear:

| Field | Values | Built as |
| --- | --- | --- |
| `seam` | `none` (default), `back`, `back-cuban` | A 3 mm line down the back of the leg, drawn in the generated texture at the UV seam, which already sits at her back. `back-cuban` adds a reinforced heel panel |
| `stockingTop` | `plain` (default, today's band), `lace`, `silicone` | The top band is already its own trim section with its own material. `lace` gives that section the lace mask pattern with an opaque lining. `silicone` is a narrow plain band, and a hint that no belt is needed |
| `denier` | a number, 10–100 | Mapped onto the existing opacity scale: 10–15 very sheer, 20 sheer, 40 translucent, 60+ opaque. So "20 denier" becomes a planner word |

Fishnet stays exactly as it is, and pairs with a `plain` or `lace` top.

### 4.5 New garments (fixes G3)

These are four new templates. No existing template changes.

| Template | Kind | Layer | Notes |
| --- | --- | --- | --- |
| `under-suspender-belt-v1` | `suspender-belt` | foundation | Belt only, 4 tabs. `belt: standard` |
| `under-suspender-belt-high-v1` | `suspender-belt` | foundation | `belt: high-waisted`, 9 cm deep, up to the natural waist, 6 tabs (look 4) |
| `under-waspie-v1` | `waspie` | foundation | A waist cincher 14–18 cm deep, from underbust to high hip, conform 1.0, 6 tabs, optional boning lines in the texture (look 4) |
| `under-guepiere-v1` | `guepiere` | foundation | A longline bustier from the bust to the high hip, cups from the existing `demi` and `balconette` necklines, 4 or 6 tabs (look 5) |

All four are `category: underwear`, so they are gated exactly as the Garter Set is
today. The waspie and guêpière reuse the measured torso fit, band building and
top-edge rules: sleeveless top edges stop at the armpit, and the neckline comes
from the cup profile.

The brief's advice for look 5, a guêpière under clothing "neither extremely tight
nor very short", becomes a planner note. When the outer layer is conform ≥ 0.95, or
`reveal: statement` is set over a guêpière, the plan says what the brief says
without refusing: *a guêpière under a skin-tight or very short outer layer will
show its lines*.

### 4.6 Sets (fixes G6)

When the prompt says *matching set*, *coordinated* or *completo*, or pieces are
joined with *matching*, the pieces share a `setId`. It is written to each node's
existing `wardrobeForge` extras beside `layer` and `role`. Colour, pattern and
finish carry as today. What is new is only the grouping. The Studio's "build on the
look on stage" can then swap or recolour the set as one unit, and Base Body Prep can
take a whole earlier set off together.

### 4.7 The five looks, as standard prompts

These are written in words the planner will understand, so each is a normal
layered prompt plus one style value. There is no preset file.

| # | Prompt | Style |
| --- | --- | --- |
| 1 | `black lace suspender belt + sheer black stockings with lace tops + black mini skirt + black fitted top` | `reveal: glimpse` |
| 2 | `black suspender belt + black fishnet stockings + black mini skirt + white fitted tee` | `reveal: glimpse` |
| 3 | `burgundy lace bralette + matching briefs + matching suspender belt + sheer black stockings + black knee-length dress` | `reveal: discreet` |
| 4 | `black high-waisted suspender belt + seamed sheer stockings + black pencil skirt + white blouse` | `reveal: discreet` |
| 5 | `black guêpière + sheer black stockings + black A-line skirt` | `reveal: discreet` |

The Studio shows them as five chips in the Style section. Each chip fills in the
prompt and the reveal control, and everything stays editable. The same list is
exposed through `/v1/vocabulary` as `ensembles`, so a client can offer them too.

## 5. Data model changes (all optional, all additive)

```python
class StylePlan:        # existing fields unchanged
    reveal: str | None = None            # discreet | glimpse | statement
    briefs_over: bool = False            # briefs over suspender straps
    seam: str = "none"                   # none | back | back-cuban
    stocking_top: str = "plain"          # plain | lace | silicone
    denier: int | None = None            # mapped to opacity; None = unchanged

class GarmentFit:       # template "fit" block, existing fields unchanged
    belt: str | None = None              # standard | high-waisted
    suspenders: int | None = None        # 4 | 6

class OutfitPlan:       # existing fields unchanged
    set_id: str | None = None            # on each garment in a coordinated set

# new layer role between legwear (2) and main (3)
CONNECTOR = (2.5, "connector")

class FitReport:        # new optional block
    hosiery: dict | None                 # see below
```

The `hosiery` block of the fit report:

```json
{
  "stockingTop": {"left": 0.672, "right": 0.671},
  "clips": {"count": 8, "maxBandDistanceMm": 1.8},
  "straps": {"restSlack": 0.015, "maxElongation": {"walk": 0.021, "sit": 0.064}, "warnings": ["left-front pulls in sit"]},
  "reveal": {"requested": "glimpse", "achieved": "glimpse", "visibleIn": ["sit"], "hemY": 0.705},
  "dressingOrder": "briefs-under"
}
```

## 6. Where it runs in the pipeline

```text
plan_outfit_stack ──► reveal words, set detection, connector layer inserted when belt + stockings
prepare_base_body ──► unchanged
fit_garment, per layer:
    foundation   belt / waspie / guêpière / bra / briefs          (briefs deferred if briefsOver)
    legwear      stockings ──► publish StockingTop
    connector    straps from belt tabs to StockingTop.clips ──► tension check in walk and sit
    main/outer   skirt or dress: hem solved for `reveal` against StockingTop + clips
validate_output ──► hosiery block in the fit report; existing checks unchanged
```

Each step runs only when its inputs exist. An outfit without a belt, stockings or
`reveal` takes exactly today's path.

## 7. Studio

In the Style section, shown only when the outfit contains legwear:
- **Reveal**: *Discreet · Glimpse · Statement*, with a line under it saying which
  poses show the band.
- **Stocking**: *Top* (plain, lace, silicone), *Seam* (none, back, back with Cuban
  heel), and *Denier*.
- **Belt**: *Standard · High-waisted*, and *4 · 6 straps*.
- **Briefs over straps** toggle.
- The five ensemble chips from 4.7.

**Check plan** gains one line: *stockings clipped · reveal: glimpse (band shows
seated) · straps within tension*.

The Judge view gains a **seated preview** toggle. It poses the look with the `sit`
rotations the pose test already uses, so "shows when she sits" can be seen, not
only read.

## 8. Verification

**Tests.** Unit tests are synthetic; the pipeline tests use the mannequin. All run in CI.
- Every clip is within 3 mm of the fitted band ring, on all four calibration bodies
  and both VRM specs.
- Change the stocking length, and the clips follow the band. This is the G1
  regression.
- Strap elongation in `walk` and `sit` stays at or under 10%, and a forced
  over-short strap raises the warning, then the error.
- For each `reveal` level, the solved hem satisfies its row of the table in all
  three poses.
- An explicit length plus a conflicting `reveal` keeps the length and reports the
  achieved level.
- `briefsOver`: straps lie inside the briefs, and nothing intersects.
- Denier words map onto the opacity scale, `seam` draws at the back, and a `lace`
  top band is a mask with an opaque lining.
- Gate: every new template is refused on an avatar with no adult declaration, the
  same way `under-garter-set-v1` is today.
- **Non-destructive**: the 81 existing gallery looks produce identical geometry
  hashes, and every existing test passes unchanged.

**Gallery.** The five looks from 4.7 are added to the mannequin verification set,
whose jobs carry the operator's adult declaration. Each is rendered standing, as
today, and also seated, with a new `pose=sit` parameter for `tools/gallery`. Each
caption carries the `hosiery` report line. As with the rest of the intimate set,
they are not rendered on the library avatars, which have no adult declaration.

## 9. Build order

| Phase | Delivers | Depends on |
| --- | --- | --- |
| H1 | `StockingTop` contract, and today's garter reading it (G1). No visible change except clips landing on measured bands | — |
| H2 | `suspender-belt` kind, the connector layer, `briefsOver`, strap rest length and the tension check | H1 |
| H3 | `seam`, `stockingTop: lace/silicone`, and `denier` | — |
| H4 | `reveal`: posed hem solving, planner words, and the fit report entry | H1 |
| H5 | High-waisted belt, `waspie` and `guepiere` templates | H2 |
| H6 | Studio controls, seated preview, `setId`, ensembles in `/v1/vocabulary`, gallery additions | H2–H5 |

Each phase ships on its own, and stays behind the gate and the non-destructive test.

## 10. Risks and open questions

- **Skirts have no cloth simulation.** Seated, a skinned skirt follows the thighs
  rather than draping, so the reveal is computed from the hem ring's skinned
  position. That is conservative for `discreet`, whose real hem rides up less than
  a rigid one, and approximate for `glimpse`. The report says the reveal was
  computed in the skinned pose, not simulated.
- **Six straps on a short thigh.** On a petite body the belt-to-band distance can
  be under 8 cm. Below that, the planner falls back to four straps and says so.
- **Reveal on a non-A-pose rest.** Reveal is solved from the rest pose plus the
  `POSE_TESTS` rotations, which assume a T or A rest. Other rests are rejected
  earlier by the pipeline already.
- **Open: should `statement` also allow a mini over a guêpière?** The brief advises
  against it, but does not forbid it. Proposed: allow it, with the planner note from
  4.5.
