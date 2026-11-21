# BD1 — Body-detail variants on a bare body

On 2026-11-18 the owner chose generated detail for the undressed body, reversing
the deferral recorded in `BARE_BODY_PLAN.md`. They asked for more detail, in
variants, with no pubic hair, readable when zoomed and in every position.

## What it is

`wardrobe/vrm/body_detail.py` paints the detail into her own skin texture and its
MToon shade texture, on a bare look only:

- areolae and nipples, with Montgomery glands
- the vulva: outer and inner labia, clitoral hood and glans, urethral meatus,
  vaginal opening
- the perineum and the anus

Proportions come from published clinical measurements of adult women (Lloyd et
al., *BJOG* 2005), written for a 1.63 m body and scaled to hers.

No vertex moves, no mesh is added, no accessor changes. The bare path
fingerprints them and still does. Every texel that is painted knows the point of
her body it shows: the triangles near the landmarks are rasterised in UV space
with their rest-pose positions interpolated. So placement is decided in metres on
her body and is independent of the UV layout. The paint is part of her skin, so it
moves with her in every pose.

**Landmarks are measured, not typed:**

- **Nipples:** the most forward skin point of each side of her chest, in the band
  adult proportions put them (66–79 % of her height, 2.5–9 % out from her
  midline).
- **Crotch:** the lowest skin point on her midline, snapped to the axis through
  her hips.

**Zoom.** Below 4 texels/mm around the landmarks, the skin texture and its shade
texture are resampled at twice the size, up to 4096.

## Relief (BD2)

Paint alone cannot show a fold or an opening under light, so the same anatomy
fields also give a **height field** in metres:

- **Raised:** nipple dome, areola, outer labia, the inner labia's ridges,
  clitoral hood and glans.
- **Recessed:** the cleft, the vaginal opening, and the anus with its radial
  folds.

Its gradient on her surface becomes a **tangent-space normal map**. The tangent
frame is built per triangle from its UV derivatives (T along +u; Y up the image,
as glTF has it), so it holds on any UV layout and across island seams. A normal
map she already has is kept, with the relief blended over it (whiteout).
Otherwise one is added: core `normalTexture`, and VRM 0.x `_BumpMap` with its
`_NORMALMAP` keyword. `relief` in a preset scales it; 0 is paint only. Rendered,
the nipple is lit from above and shadowed below, and the vulva's folds catch the
light.

## Variants

`assets/body_detail/presets.json` has nine presets.

**Hairless (four):** `natural`, `soft-pink`, `warm`, `defined`. They vary areola
size and tone, the inner labia's size and tone, the opening and anus size, and
perineum length.

**With hair (BD3, five):**

| Preset           | Hair style                             | Colour      |
| ---------------- | -------------------------------------- | ----------- |
| `natural-hair`   | full natural, down the outer labia     | dark brown  |
| `trimmed`        | short, sparser, on the outer labia too | mid brown   |
| `landing-strip`  | narrow strip                           | dark        |
| `triangle`       | neat groomed triangle                  | near-black  |
| `auburn-natural` | full natural                           | auburn      |

Hair is drawn as strands, not speckle. Each texel sits in a flow field running
down and in and curling slowly, and thin cells along it are strands, tapered,
each with its own tone. A strand is at least a texel wide, because thinner ones
alias into scratches. A soft coverage shadow lies under them, so the hair reads
from any distance. Groomed styles have a crisp edge; natural ones feather out.

Tints multiply her own skin colour texel by texel, so a preset suits every skin
tone and keeps her shading.

A job asks for one with `options.bareDetail`. That option is valid only with
`baseBody: "bare"` and only names a preset in the file. Unset is the default, so
no stored cache key changes. The look carries
`extras.wardrobeForge.detail = <preset>`, and the fit report carries
`baseBody.bodyDetail`: landmarks, texels/mm, whether the texture was resampled,
and the clearance used.

## Body states (BD4)

`assets/body_detail/states.json` defines states that are painted on top of any
preset (`options.bareState`, which needs `bareDetail`). Each sets three
parameters, from 0 to 1:

- **`arousal`:** a flush towards red, swollen inner lips, a larger glans, and a
  wet sheen down the vestibule.
- **`vaginaOpen`:** the inner lips part and the opening widens and lengthens. It
  shows the inner walls (flushed, with transverse folds) round a centre that
  darkens and deepens as it opens.
- **`anusOpen`:** the anus relaxes open. Its radius grows, the folds stretch flat,
  the pinker inner rim shows, and the centre widens and deepens.

| State       | arousal | vaginaOpen | anusOpen |
| ----------- | ------- | ---------- | -------- |
| `closed`    | 0       | 0          | 0        |
| `aroused`   | 0.85    | 0          | 0        |
| `open`      | 0.9     | 0.65       | 0        |
| `wide-open` | 1.0     | 1.0        | 0        |
| `anus-open` | 0.5     | 0          | 0.7      |
| `both-open` | 0.9     | 0.65       | 0.7      |
| `stretched` (fisting) | 1.0 | 1.5     | 0        |
| `anus-stretched` (fisting) | 0.9 | 0 | 1.5      |

The openings go up to 1.5 (BD8): past 1 is stretched beyond wide open, for the
two fisting states. Each state has a `body` line in the second person ("you are aroused and open:
…"), for the conversation. A client says it to the model only while that look is
on stage, the same way the positions describe her body. The look carries
`extras.wardrobeForge.state`. Rendered from behind on all fours, the six states
are distinct; Knees Up framing in the render tool still needs work.

## Her skin reacting (BD5) and tan lines (BD6)

`wardrobe/vrm/skin_effects.py` adds effects across her whole torso band, from
below her buttocks to her throat. They are painted in this order: tan lines
(her skin), then the flush, then the anatomy, then sweat on top.

**State parameters (0–1):**

- **`flush`:** a blotchy blush over her breasts and up her chest to her throat.
- **`erect`:** a taller nipple and a finely puckered areola, in the relief.
- **`goosebumps`:** fine bumps in the relief.
- **`sweat`:** a sheen (between her breasts, in streaks) and beads, each a
  highlight with a faint rim below and a little relief.

**States:**

- **New:** `flushed`, `goosebumps`, `sweaty` (labelled "Glistening"), and
  `afterglow`.
- **Updated:** `aroused`, `open`, `wide-open` and `both-open` now carry a flush
  and erect nipples too.

**Extras** (`assets/body_detail/extras.json`, `options.bareExtras`, up to four)
are persistent, unlike states. They are tan lines, as paler bikini shapes:

- **Tops:** `triangle` (two cups, halter straps, a band all round) and
  `bandeau`.
- **Bottoms:** `thong`, `brazilian` and `classic`, with a waist string all
  round; a thong is a string down her cleft behind.
- **Presets:** `tan-triangle-thong`, `tan-triangle-brazilian`,
  `tan-bandeau-classic` and `tan-thong-only` (topless). Each has a `body` line
  for the conversation.

Painting the torso band is heavier: about 30–40 s per look at 4096, against
about 8 s for anatomy alone. A parameter at 0 costs nothing. Rendered front,
chest and back on the reference body: every effect shows where it belongs.

## Marks, writing, piercings, variety and tattoos (BD11–BD12)

New extras (persistent, `options.bareExtras`):

- **Lipstick kisses:** `kisses-red` and `kisses-pink`. Lip-shaped prints with a
  cupid's bow and faint lip lines, on breasts, belly, inner thigh and buttock.
- **Love bites:** `love-bites`, on the neck, a breast and the inner thigh.
- **Spank:** `spanked`, a soft pink handprint on a buttock.
- **Realistic skin:** `freckles`, which also adds three beauty marks and fine
  pores in the relief.
- **Body writing:** `writing-yours` ("YOURS" in marker on the belly) and
  `writing-lower-back` ("MINE" in lipstick). The text is rasterised once and laid
  across her own lateral and vertical position, not UVs.
- **Piercings:** `piercings-nipples` and `piercings-all` (nipple barbells, a
  navel jewel, a clitoral-hood ring). These are painted steel with a highlight
  and raised relief, not separate meshes.

New presets: `outie` (inner lips that show) and `puffy` (puffy areolae, raised
by `areolaPuff`).

**Tattoos (BD12).** Forge's body-art system (`bodyArt`) is now accepted on bare
and bare-dressed jobs, so intimate placements (lower back, under the bust, ribs,
thighs) can be worn bare. The exposure check still places each one only where
her skin shows.

Rendered: writing, the barbells, the navel jewel, the kisses and the handprint
read well. Freckles and love bites are subtle at full-body distance.

## Pumped, oiled, intimate tattoos and piercings (BD13)

New states (`states.json`, live-switchable in a skin pack like any other):

- **`pumped` and `pumped-open`:** the deformation a vacuum pump leaves. `pumped`
  (0..1) widens the outer lips by up to a third and nearly doubles the inner lips
  (`_minora_width`), lengthens them a little, and swells the glans
  (`_glans_radius`). The tints go deep red-violet and glossy, and the relief
  rises. Colour and relief read the same helpers, so a fold is where its colour is.
- **`oiled` and `oiled-aroused`:** a massage-oil sheen over her whole torso band,
  with long glossy highlights and no beads. The highlight tints lift blue and
  green more than red: on already-bright skin a flat multiplier clips red first
  and the shine turns cyan (seen and fixed).

New extras (`extras.json`):

- **Mons tattoos:** `tattoo-mons-heart`, `-rose`, `-butterfly` and `-text`
  (`tattoo`: one of `TATTOOS`; `tattooText`, `tattooInk`). Each is a PIL drawing
  (black linework over a colour fill, with green leaves for the rose) sampled
  bilinearly at her own coordinates. `_mons` gives across her midline and up her
  front, along her skin, and the design sits just above the vulva. A natural
  bush paints over it, as hair would.
- **Intimate piercings:** `piercings-labia` (two rings in each inner lip, which
  follow a pumped or opened width), `piercings-christina` (a vertical bar up the
  mons with a gem at its foot), `hood-bar` (in `piercings-intimate`) and
  `piercings-nipple-rings` (rings hanging through the nipples).
  `skin_effects.PIERCINGS` lists what may be worn, and `load_extras` refuses
  anything else. Piercings from several extras now add up instead of the last
  one replacing the rest.
- **`hearts`** (lipstick hearts at the kiss spots), **`glitter`** (gold, blue and
  pink flecks over her chest and belly), **`body-paint-gold`** (flowing lines;
  `bodyPaintColor`), and **`stretch-marks`** (fine, pale, broken lines across her
  hips and under her breasts, a hair below the surface in the relief).

**Not paintable, so not here.** A bottle or any other inserted object needs a
prop mesh attached to her pelvis bone: it is a separate feature, not skin. The
`stretched` states paint the skin as it looks around one. Breast-shape changes
and real mesh jewellery also change the mesh, which this painter never does.

## Missionary and cowgirl: facing them (BD20)

Ten states for the two positions where she faces them. In missionary she is on
her back, seen from above: face, breasts, belly, open vulva. Cum on her belly
runs off her sides (`cumRunSides`), and a creampie runs down to her anus. In
cowgirl she is upright on top, seen from below: cum on her belly runs down over
her mons (`cumRunDown`), and a creampie runs down her inner thighs
(`cumThighs`). `cumBelly` is a pool in her navel with ropes across her belly,
and `cumChest` is ropes across her breasts pooling in her cleavage.

| Missionary            | Cowgirl              |
| --------------------- | -------------------- |
| `missionary-open`     | `cowgirl-riding`     |
| `missionary-creampie` | `cowgirl-creampie`   |
| `missionary-belly`    | `cowgirl-belly`      |
| `missionary-chest`    | `cowgirl-after`      |
| `missionary-covered`  | `cowgirl-everything` |

Missionary also has three fisted variants: `missionary-fisted` (vagina
stretched to 1.5, lips swollen by `pumped`), `missionary-fisted-anal` (the BD16
gape) and `missionary-fisted-cum` (stretched and filled, running down to her
anus).

All ten keep her open, suit every preset (a hairless one shows the most), and
switch live in a skin pack. The chatbot's finish chooses among them by the
position she holds (UN37). `detail_flat.py --views thighs` shows her lower belly,
vulva and inner thighs from the front.

## A second load, and sweat that builds on her back (BD19)

`cumSecond` lays a second load on her back with ropes at other heights, leaning
the other way so they cross the first, and its pool a little higher. Under it
the first load thins to a glaze: less thick, so translucent and dull, while the
new one is thick and pearly. `sweatBack` builds on her back while she is held on
all fours: a glistening line down the groove of her spine, damp patches, beads
that gather low down, and a warm flush over the small of her back and her
cheeks. It is only ever on her back. States: `doggy-sweaty`,
`doggy-sweaty-open`, `lower-back-cum-second`, `doggy-second-creampie`. The
chatbot switches to them live: sweat after a while held on all fours, and the
second load when the person finishes on her back again (UN35).

**Admin panel (BD18).** Forge Studio has a "Private · bare body variants" panel
for an admin session. It offers an erotic set or bare, a detail preset, a body
state, extras (up to 4) and live states (up to 10), with Generate and Run again.
Its lists come from `GET /v1/admin/body-detail`, which reads these files, so a
new state or extra appears there without touching the page.

## Lower-back cum, fisted anus, sado, tribals, white and anime skin (BD15–BD17)

**Lower-back cum (BD17).** In doggy her ass is up and her chest down, so her
back slopes down from her hips to her shoulders. `cumPool` is a thick pool in
the small of her back, above her cleft. What overflows runs up her spine
towards her shoulders (`cumSpine`), down her flanks (`cumSides`), and down into
her crack (`cumCrack`). Each run narrows and breaks into drops with a bead at
its end. States: `lower-back-cum`, `lower-back-cum-heavy`,
`lower-back-cum-open` (both holes open), `lower-back-cum-creampie`,
`lower-back-cum-gaping` (with the fisted anus). They pair well with
`tattoo-lower-back-tribal`.

**Fisted anus (BD16).** `anusGape` (0..1) widens the anus to about 1.85× its
stretched size (`_anus_radius`). It is a round gape: folds gone, a swollen red
rim with a wet edge, pink inner walls, a dark centre and deep relief, so it reads
from behind on all fours. States: `doggy-anal-fisted`, `doggy-anal-fisted-cum`,
`doggy-both-fisted`. `anusCumInside` fills the same, wider opening.

**Sado (BD15).** `ropeMarks` (shibari: bands above and below the breasts, a
diamond harness down her belly, the spine line and thigh bands, pressed in),
`wax` (red candle wax on her breasts and belly, glossy and raised), `welts`
(raised whip stripes across her buttocks, the backs of her thighs and her lower
back), `clampMarks` and `collarMark`. States: `sado-roped-open`,
`sado-wax-open`, `sado-whipped-open`, `sado-used-cum` and `sado-full`. Every one
of them has both holes open.

**Tribals (BD15).** `tattoo-lower-back-tribal-wings`,
`tattoo-lower-back-tribal-sun` and `tattoo-mons-tribal` (`tattooPlace`: `mons`
or `lower-back`; `FX.TATTOO_PLACES`).

**White and anime skin (BD17).** Her skin colour is the avatar's own texture:
choose a pale avatar for white skin. The presets match the anatomy to it.
`porcelain` has light pink areolae and labia for white skin. `anime` is soft,
simple and pink, with lower relief (0.6) so toon shading stays clean. Both are
hairless.

**Thin and fat.** Body shape is the avatar's mesh. Every size here is measured
from her landmarks and scaled to her height, so the detail follows a thin or a
full figure without a separate preset.

## Doggy style: from behind, on all fours (BD14)

States for the all-fours view, where her buttocks, lower back, both openings
and inner thighs are what is seen. All of them suit a hairless preset
(`natural`, `soft-pink`, `warm`, `defined`, `outie`, `puffy`). None of them
carries handprints or grip marks: the owner asked for none.

| State                   | Both open | What the cum does                                                    |
| ----------------------- | --------- | -------------------------------------------------------------------- |
| `doggy-open-cum`        | yes       | pooled on both openings, running between them, dripping forward      |
| `doggy-double-creampie` | yes       | both filled (`cumInside`, `anusCumInside`) and leaking forward       |
| `doggy-gaping-cum`      | 1.5 each  | both stretched gaping and full, more pooled round them               |
| `doggy-cum-covered`     | yes       | both dripping, plus ropes across her back and buttocks (`cumBack`)   |
| `doggy-pumped-creampie` | yes       | pumped (BD13) labia, both filled, running over the swollen lips      |
| `doggy-finish`          | yes       | everything above at once                                             |
| `doggy-creampie`, `anal-creampie`, `cum-on-back` | one | one opening, or her back |

New fields (`skin_effects.fluid`):

- `cumDrip`: gravity on all fours pulls towards her belly, so what leaks runs
  forward over her vulva and clit, meanders, breaks into drops, and hangs off
  her mons.
- `anusCumInside`: the opened anus, at BD4's own size, is filled and leaks
  forward over the perineum.
- `cumBack` (`_on_her_back`): lumpy ropes across her lower back and buttocks,
  tapering and breaking up at their ends, a pool in the small of her back, and
  thrown droplets.

The new extra `tattoo-lower-back-tribal` puts a symmetric black tribal
(`tattoo: tribal`, `tattooPlace: lower-back`) across the small of her back,
above her cleft: the view from behind. Wear it with a doggy skin pack
(`bareExtras` with `bareStates`). `spankRed` and `grips` exist in the painter,
but no state uses them.

## Semen (BD9)

The `cum` parameter, and the `cum` state, paint semen on her body skin:

- **Where:** pooled at the vaginal opening and at the anus, running between them
  over the perineum and on below, breaking into drops, with strands across the
  vulva and droplets round both openings.
- **How:** a thickness field decides everything. Thick cores are opaque and
  pearly, thin edges translucent, and a highlight sits where it is thickest. The
  relief raises it about a millimetre.
- **Inside (BD10):** `cumInside` fills the opened vaginal opening (sized as
  BD4 opens it): opaque across the centre, a wet meniscus at the inner walls, a
  run spilling over the lower edge. States `creampie` (and `cum`, which now
  includes it).
- **Limit:** the mouth is on her face material, which this painter does not
  touch.

## Live state switching: skin packs (BD7)

`options.bareStates` (needs `bareDetail`, up to ten) builds a **skin pack**
beside the look. Every listed state is painted on her prepared bare body, before
any detail, with the look's own preset and extras.

- **Tiles.** Each state is diffed against that body, and only the 256-texel
  tiles any state changes are kept. Every state stores the same tiles (the
  union), so switching from any state to any other leaves nothing behind.
- **Files.** `skin-pack/manifest.json` plus `skin-pack/<state>/<map>.png`, under
  the look's key and served as privately as the look itself.
- **Manifest.** It gives the skin material's name, the texture size, the tile
  list, the maps (base, shade, normal), and each state's label and `body` line.
- **Tags.** The look carries `extras.wardrobeForge.skinPack`, and the fit report
  carries `baseBody.skinPack` (states, tiles, maps, bytes).
- **Client.** The chatbot's `SkinStateSwitcher` draws a state's tiles over a
  canvas copy of her skin and swaps it in live, with no reload.

On the reference body at 4096, a four-state pack is 99 tiles and about 4.4 MB
per state, built in about 2 minutes.

## Who it is painted on

Painted detail is more explicit than the bare body, so it asks for more than the
bare gates. `eligibility.detail_clearance` accepts:

- a person's `clearly-adult` finding for the exact file that carries its
  **review packet** and at least **40 characters of evidence**, or
- Forge's own synthetic adult reference body.

It is asked before any work. A refusal is `refusedBy: detail-review`.

The registry entries recorded on 2026-11-17 (reviewer "John", evidence "Its okay
is adult", no packet) open the bare body but do not paint detail. The registry is
write-once per file (`record_review`): to redo a character's review, remove its
old entry first, then record the new finding with `tools/body_surface/gates.py`
and its packet.

## Her anus in detail (BD23)

`_anus_folds` adds what a close look from behind expects: eighteen radial creases of uneven
depth, sharpest near the centre, plus the darker, browner ring of skin round it (`perianalTint`)
and a faint wet sheen between the creases. As she relaxes open the creases flatten, and under a
gape they are covered. Colour (`_pelvis`) and relief (`_height`, each crease cut in) read the
same helper. It is in every detailed look, not a state of its own. The look from before BD23 is kept as the
**Classic** preset (`anusDetail: 0`, Natural otherwise): pixel-identical to the old painting,
checked in the flat view. Checked in the flat view
before and after: closed, relaxed open, and after the fist.

## Wrecked past a fist, and a gaping vagina (BD22)

- `anusGape` now goes past 1 up to 1.5 (`_wreck`). Past a fist, the rim puffs up thick in six
  uneven lobes, deep red. The inner walls get a wet gloss line, and the centre goes darker and
  deeper. Relief reads the same helper.
- `vaginaGape`, from 0 to 1.5 (`_vagina_gape`), rounds the opening out and holds it open. The
  rim is swollen and flushed, the walls glossy, the centre dark, and the inner lips swell too.
  It widens `_introitus` and `_minora_width`, so colour and relief move together.
- Swelling, redness and wetness only, never a tear or blood. `tests/unit/test_gape_bd22.py` holds
  the ranges and checks that no state using them mentions injury.
- Used by the from-behind states (`doggy-bottle*` at 1.5 and 1.3; the fisted pussy at 0.7).
  What matters is how her body looks afterwards; no object is ever painted.
- Checked in the flat view: the wrecked anus reads clearly wider and redder than the fisted one,
  and filled reads too. The lobes, and the pussy gape at 0.7 against 1.3, do not read on the
  reference fixture: its texels are sparse just there. Judge them on a real character with a
  detail review.

## Checked

- `tests/unit/test_body_detail.py` (16): presets (hairless and one per hair
  style), the option, the clearance (placeholder refused; packet and evidence
  both needed; synthetic reference accepted), measured landmarks, paint present
  where anatomy is and absent elsewhere, rasteriser interpolation, the relief's
  heights (raised and recessed where the anatomy is, flat elsewhere), its normals
  (flat where nothing is, leaning the right way over a bump), the tangent frame's
  orientation, and the hair styles' relative coverage.
- `tests/integration/test_bare_body.py` (`-k detail`, 2): refused without a full
  review and before any paint; painted last, with her facing, and tagged.
- **Rendered** in the chatbot's three-vrm/MToon viewer on `ref-f-median`, Forge's
  synthetic adult. The test copy had a skin texture and unique per-triangle UVs at
  about 2 texels/mm: the reference body's own cylindrical UVs overlap, which
  duplicated the vulva onto her inner thighs. Views: chest close-up, and the
  pelvis in Sitting Open, Knees Up and All Fours. All four variants were
  distinguishable, the anatomy was in place, and the tones were natural after one
  tuning pass.

## Limits

- **Relief, not geometry.** A normal map changes how light falls, not the
  silhouette: an opening reads as recessed, but a profile view is still the
  mesh's own line. Same-topology morphs cannot carry millimetre detail (pelvic
  edges are 16–24 mm).
- **Not yet rendered on a library character.** None has a full review yet.
- **Placement on unusual bodies.** It assumes an adult-proportioned rest pose.
  When a landmark cannot be found, the job is refused (`body detail could not be
  placed`); nothing is guessed.

## Tools (for the next session)

- **Previews:** `python tools/body_surface/detail_preview.py --out <dir> [--presets a,b] [--base ref-atlas.vrm]`
  builds every preset on Forge's synthetic adult with unique UVs (five minutes
  the first time; `--base` reuses the atlas body). The output is explicit and
  private: never commit it.
- **Close-ups:** in the chatbot,
  `node tools/qa/body-detail-render.mjs --vrm audits/poses/runs/detail/ref-<preset>.vrm --views chest,seated,kneesup,allfours`
  renders them in the app's own viewer and poses, the camera aimed along each
  landmark's surface normal.
- **Flat check (seconds, no renderer):**
  `python tools/body_surface/detail_flat.py --base <dir>/ref-atlas.vrm --out <dir> --preset natural --states pumped --extras tattoo-mons-rose+piercings-intimate --views pelvis,nipple,torso`
  paints in memory exactly as `paint_detail` does and plots each texel at her own
  coordinates: the vulva unrolled along her midline, a nipple face-on, and her
  torso front. Tune with it first, then confirm in the viewer. `detail_preview.py`
  also takes `--states` and `--extras` (`+` joins extras worn together, `,`
  separates variants).
- To tune a preset, change `presets.json`, rebuild that preset with `--base`, and
  render it. Change the anatomy fields in `body_detail.py` (`_pelvis`, `_height`,
  `_hair`) and run `tests/unit/test_body_detail.py`.
- **Anatomy probe (seconds, a real body):** `tools/body_surface/anatomy_probe.py`
  `landmarks` (is her crotch on her midline seam?), `mesh` (vertices, bones and
  facing round her anus), `midline` (her skin along the midline), `layers`
  (paint landing below her crotch, off her midline, or on thigh-moved skin).
- **One exact pack in the chatbot, nothing published:** `tools/qa/verify_pack.sh`
  (local Forge with `WARDROBE_HF_PUBLISH=false`, the look worn by id and hash),
  then `tools/qa/compare_frames.py` for before/after from the same camera.

## The thigh bands and the open ring (BD24–BD29)

What Avatar A's red bands down her inner thighs (Step 5 rear views, all fours,
face down, bent over) turned out to be, in the order it was learned:

1. **BD24** masked anus paint below her crotch: thinner bands, still there.
2. **BD26** guarded skin her thighs move (skin weights, `_thigh_keep`): measured
   on her skin, the remaining red sat on skin 1-2 cm beside the anus that the
   thighs move 50-90%; bending the legs stretched it.
3. **BD27** drew every anus layer inside a compact patch (`_anus_patch`, ~3 cm):
   thighs clear, but the anus vanished.
4. **BD28** added a new kind, the open ring after a fist (`anusRing`, states
   `doggy-anal-ring`, `-ring-cum`, `doggy-both-ring-cum`, pack `ring`): nothing
   showed. `anatomy_probe.py midline` found no skin where its centre was drawn.
5. **BD29, the cause:** `find_landmarks` took the lowest point within ~1 cm of
   her axis as her crotch. Where a VRoid body's thighs meet near the midline
   (Avatar A), that is a thigh's inner edge, 4 cm under her real crotch (B 1.3,
   fem 1.6, masc 1.8 cm). Every anatomy distance was measured from under her
   body. The crotch is now the lowest vertex on the mesh's exact seam. With it
   the ring's centre and rim land on skin her hips move (thigh share ~0.01) and
   no mask has to cut anything.

Lessons: measure the body before changing the paint; a test on a synthetic body
cannot show a landmark that is wrong on a real one; every look painted before
BD29 has its anatomy lower than it should be and needs repainting, front and back.

## The fist, then the finish (BD31, BD32)

States for the chatbot's stories, each in the pack its first state is in, so the whole story
switches live in one look:

| After their fist in her… | then they finish… | state | pack |
|---|---|---|---|
| ass (`doggy-anal-fisted`) | in her pussy | `doggy-anal-fisted-creampie`: ass gaping, empty | fist |
| ass, the ring (`doggy-anal-ring`) | in her pussy | `doggy-ring-creampie` | ring |
| pussy (`doggy-fisted`) | in her ass | `doggy-fisted-anal-cum`: pussy gaping, ass full | fist |
| both, tied and marked (`sado-both-fisted`) | anywhere | `sado-both-fisted-cum`: rope lines, welts, both full | rough |

The chatbot picks them in `PrivateActionBridge` `AFTER_ANAL_FIST`; its shows are
`fist-then-inside` (Valentina), `worse-than-last-time` (Chiara), `fist-then-ass` (Valentina),
`two-hands` (Valentina, BD33, shown as "Legata e spalancata": tied, marked, both hands, green/yellow/red).
Check them with `tools/qa/verify_set.sh tools/qa/checks/painter.txt <out>` (line `stories-a`).
