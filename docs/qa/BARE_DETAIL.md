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

Each state has a `body` line in the second person ("you are aroused and open:
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
- To tune a preset, change `presets.json`, rebuild that preset with `--base`, and
  render it. Change the anatomy fields in `body_detail.py` (`_pelvis`, `_height`,
  `_hair`) and run `tests/unit/test_body_detail.py`.
