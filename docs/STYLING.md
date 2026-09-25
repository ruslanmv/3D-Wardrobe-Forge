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
- **Modes:** `preserve` layers over her outfit, `replace-outer` (default) takes
  off what the outfit covers, `underwear-base` also puts a neutral foundation on
  first. **No mode outputs her with nothing on**, the stripped state is never
  stored, and the stored source is byte-identical after every job.
- **Provenance:** the look records the base-body mode, which of her garments came
  off and the layers put on; the fit report has an entry — and a design sheet —
  per layer.

## What is gated, and by whom

Swimwear, underwear and **anything the body shows through** — a sheer dress,
unlined lace, fishnet — need both the model's own terms to allow it and an
operator's declaration that the avatar depicts an adult. The gate follows what
will render, not the category name: an opaque bodycon dress is a dress; the same
dress sheer is gated. The declaration lives in `assets/library/policy.json`,
shipped empty — it is the operator's decision, recorded by them, never the
browser's. The engine models garments on the authored body; it never adds or
reconstructs anatomy.
