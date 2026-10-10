# Styling and layered outfits

How a look's material, cut and layers are decided and built. The product
overview is in the [README](../README.md); how garments are fitted to a real
avatar's body is in [FIT_QUALITY](FIT_QUALITY.md).

## Materials that survive a toon shader

The avatars this project dresses are cel-shaded MToon, and a garment borrows the
avatar's own MToon so it shades like her clothes. MToon has no roughness and no
metalness, so "latex" used to render as flat colour. A finish is now written in
the terms a toon shader *has*: a parametric rim and an additive **matcap**
(crisp-edged, the anime convention for latex and gloss), with deeper shade for
shine to read against. See-through fabric is alpha blending; lace and fishnet are
alpha-masked holes; stripes, dots, gingham and plaid are colour baked into a
tiling texture. Textures are **generated** — numpy and a 60-line PNG writer, no
image assets, byte-identical every run — and UVs are metres of fabric, so a
fishnet diamond is 1.4 cm on a stocking or a bodysuit, on any avatar, with the
seam at her back. Both engines are handed the same resolved material.

Opacity follows the designers' scale — *slightly sheer* 0.8, *translucent* 0.7,
*sheer* or *chiffon* 0.55, *transparent* 0.45, *very sheer* 0.35; an explicit
value can go to 0.2, and anything lower is clamped and reported. *Sheer lace* is
unlined lace (open holes); *lined lace* is honoured even on lingerie. On a
see-through garment the straps, ties and elastic stay opaque as their own
material, the shell is built finer, and the Blender engine does not mask the body
under it.

## Cut, coverage and straps as parameters

"Micro" is a coverage, not a category: a micro bikini is a bikini at 0.58. Edges
need not be horizontal — V, plunge and sweetheart necklines, low backs, high-cut
and thong leg lines, triangle cups on a string band — and straps are networks:
halter, string ties, cross-back, garter belt with suspenders, harness. New shapes:
catsuit and leggings, fitted round each leg's own bones.

## Base Body Prep: undress once, dress in layers

A VRoid avatar arrives dressed. One job now takes off what the new outfit
replaces and puts the whole outfit on, inner first:

```text
garment inventory ─► strip plan for the whole outfit ─► is there a body under it?
   (Forge tag > Forge marker > VRoid name;          no → keep it on, or refuse the job
    anything unrecognised is never removed)               — nothing is generated in its place
        ─► measure once ─► foundation ─► legwear ─► main ─► one-piece ─► outer ─► one VRM
```

- **The whole outfit decides.** A bra alone never takes off a one-piece dress; a
  bra, briefs and a dress together do.
- **Layers stay layers.** Each fitted layer joins what the next must clear, so the
  dress goes over the underwear, and the underwear is still there — visible under
  a sheer dress. Forge garments are tagged, so a later outer layer leaves them on.
- **Modes:** `preserve` layers over her outfit ("Keep her clothes on"),
  `replace-outer` (default, "Replace what this look covers") takes off what the
  outfit covers, `underwear-base` ("Underwear underneath, then the outfit") also
  puts a neutral foundation on first where the outfit names none. None of them
  means "take her whole outfit off": briefs replace her bottoms and leave her top,
  and a plain "underwear" is a bra and briefs, which replace both. The Studio does
  not offer `underwear-base` while designing underwear or swimwear, which are the
  foundation already. **No mode outputs her with nothing on**, the stripped state
  is never stored, and the stored source is byte-identical after every job.
- **Provenance:** the look records the base-body mode, which of her garments came
  off and the layers put on; the fit report has an entry — and a design sheet —
  per layer.

### Clothes painted on her skin (PB1)

Taking her garment *meshes* off is not always taking her clothes off. VRoid
avatars often have clothing painted into the **skin texture** under the
garments, and it stays when the meshes go. On the library's eight avatars:

| Avatar | Painted on her skin |
| --- | --- |
| AvatarSample A | knit top, tights |
| AvatarSample B | printed crop top, shorts |
| AvatarSample C, Rinna | top and bottoms |
| VRoid Female | VRoid's default black bandeau and briefs |
| VRoid Male | VRoid's default briefs |
| AvatarSample_O | a small bra and briefs (and no body under her dress: refused before this) |
| Model Girl | nothing: bare skin under her clothes |

Lingerie on B therefore went on over a black crop top and black shorts, and the
job said "fit passed". Now, once the outfit is fitted, her torso skin is sampled
against her own arms' colour (`wardrobe/vrm/painted_clothing.py`). Every
non-skin sample that no opaque garment covers is painted clothing left in view.
Sheer and lace fabric does not count as covering.

- **Underwear or swimwear she asked for** (not a foundation added under clothes),
  outside "Keep her clothes on": more than 3% of her torso showing painted
  clothing **refuses the job** (`source_skin_has_painted_clothing`). The message
  says why and what to do: an avatar bare under her clothes, or "Keep her
  clothes on" to style it over them. Her skin is never repainted.
- **Any other outfit:** what shows is a warning, not a refusal. Those looks never
  promised bare skin.
- **Before generating**, "Check plan" shows how much painted clothing would be
  left in view, so the refusal is no surprise.

Measured: lingerie leaves 31–35% of her torso showing painted clothing on B and
A, and 16% on VRoid Female. On Model Girl it leaves 0%.

### What "fit passed" means (PB2)

A set fitted perfectly over a shirt clears her body and is valid VRM, and it is
still wrong. So the fit report now lists each check it ran
(`fitReport.checks`):

- `structure`: VRM, humanoid, weights, skeleton, recoverable source.
- `bodyPreparation`: her garments came off where the outfit replaces them, and
  there was a body under them.
- `layerOrder`: `passed` (fitted to her body), `layered` (over her clothes, on
  purpose) or `failed`.
- `skin`: `bare`, `painted-clothing-shows` or `not-checked` (no texture to read).
- `clearance`: the collision check.

A verdict sits on top (`fitReport.verdict`): `passed`, `styled` (layered over her
clothes on purpose: a valid look, not an underwear fit) or `failed`. The Studio
heads the report with it and lists body preparation step by step ("Her top taken
off · Body complete under it · No painted clothing in view · Fitted directly to
her body"). The wardrobe shelf shows **styled over her clothes** instead of
**fit passed** for such a look.

### Auto Foundation (`options.ensureFoundation`)

Off by default in the API, on by default in the Studio ("Foundation underneath").
It makes sure a foundation is on her under the new clothes, and adds only what is
missing:

```text
the outfit covers her upper and/or lower body?  no (shoes alone) → nothing added
        │ yes
        ▼
regions wanted = what the outfit covers
               + what her own garments reach, where the outfit covers part of them
        − what the outfit brings as its own foundation (a bikini, a lingerie set)
        − what a Forge foundation she already wears covers (kept)
        ▼
a neutral half for each region left:
    declared adult  → beige seamless bralette / beige seamless briefs
    any other       → beige seamless tube top / beige slip shorts (clothes: no gate)
```

The added pieces are innermost, with the `foundation` role. A later job leaves
them on under its clothes: only a new foundation replaces a foundation. So:

- On a look with a foundation, changing the top (`baseLookId`) changes only the
  top. The jeans and the foundation are carried.
- A bikini replaces the foundation rather than going over it.
- A job on a look that already has one adds nothing.

The body under her own clothes is checked before anything comes off, as for every
job. The stored source is never modified.

**A top that is really a dress.** VRM has no clothing slots. VRoid files Model
Girl's flared dress as `Tops`. A VRoid `Tops` whose *visible* hem reaches 45% of
the way from her hip joint to her knee is read as covering her lower half too
(`garment_inventory.DRESS_LENGTH_SHARE`): Model Girl's reaches 65%, the
library's real tops 2–28%. A skirt alone cannot take such a dress off, because
her chest would be bare. With Auto Foundation the upper half of a foundation goes
on and the dress comes off. Without it, the dress stays and the skirt goes over
it, as it always has.

**What is drawn, not what is in the buffer.** A triangle her textures cut away
(`alphaMode` `MASK`/`BLEND`) is not her body to fit round
(`wardrobe/vrm/visible.py`). Model Girl's dress hangs an invisible sheet to her
shins. AvatarSample A's Bottoms has another round hers. Read as body, these pushed
skirts out into bells and boots into drums.

## What is gated, and by whom

Swimwear, underwear and **anything the body shows through** — a sheer dress,
unlined lace, fishnet — need both the model's own terms to allow it and an
operator's declaration that the avatar depicts an adult. The gate follows what
will render, not the category name: an opaque bodycon dress is a dress; the same
dress sheer is gated. The declaration lives in `assets/library/policy.json`,
shipped empty — it is the operator's decision, recorded by them, never the
browser's. The engine models garments on the authored body; it never adds or
reconstructs anatomy.
