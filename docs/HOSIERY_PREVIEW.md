# Hosiery preview: asset and render upgrades

**Status: built. See [HOSIERY](HOSIERY.md) for what ships and §11 there for where it departs from this design.** This document extends
[HOSIERY_STYLING](HOSIERY_STYLING.md), which specifies the garments and the reveal
control. It covers the assets and the rendering needed for a hosiery look's preview
to reach the reference quality: a bodycon mini dress over sheer thigh-high
stockings, with wide stocking tops and black suspender straps and clips showing
below the hem. The belt is hidden under the dress. All changes are additive, as in
the parent document.

## 1. What the reference preview is made of

Taken apart, the reference is six things. The Forge has some of them:

| Element | In the reference | In the Forge today | Gap |
| --- | --- | --- | --- |
| Outer layer | Red bodycon mini, hem about 5 cm above the stocking tops | `dress-mini-bodycon-v1`, measured fit | The hem is not placed against the stockings (the `reveal` control, HOSIERY_STYLING §4.3) |
| Belt | Hidden under the dress | Belt band in `build_garter` | Occlusion is free in 3D: the dress is fitted outside the belt, so it covers it |
| Straps | Flat black elastic, about 9 mm wide, 4 visible at the front, slight slack | Round tubes, 2 × 3.8 mm radius | **Flat ribbon profile**, laid on the thigh surface |
| Clips | Silver slider and clasp where each strap meets the band | None | **Hardware kit** (§2.2) |
| Stocking tops | Opaque black welt, about 5 cm, with a crisp edge | A 3.5 cm opaque band section | A **wide** option, and an edge line |
| Sheer legs | Warm skin through a dark veil, darker at the sides of the leg | Uniform blend opacity | **Denier falloff** baked into alpha (§2.4) |

So the reference is reachable in 3D, as geometry and materials. It does not need a
2D compositing step: the belt is hidden because the dress really is outside it.

## 2. Asset upgrades

All of these are procedural and generated at the avatar's measurements, like the
rest of the library. There are no binary garment assets to license, and nothing
changes for a look that does not ask for them.

### 2.1 Flat straps (`ribbon`)

A new primitive next to `sweep`. It is a path with a rectangular cross-section
(width × thickness), rolled so its wide face lies on the surface it crosses:

```python
def ribbon(path: np.ndarray, normals: np.ndarray, *, width: float, thickness: float,
           max_spacing: float | None = None, name: str = "ribbon") -> Mesh
```

- `normals` come from the thigh surface under each path point. They are read from
  the measured leg sections (`lowerBody`) the trousers already use, so the strap
  lies flat on the leg and does not twist.
- Default size: 9 mm × 1.2 mm, scaled by height / 1.6 m. `strapWidth` is an
  optional fit field.
- Used by the connector layer (HOSIERY_STYLING §4.2), and available to bra straps
  and halter ties later. Existing strap styles keep their round tubes unless a
  template asks for `strapProfile: flat`.

### 2.2 Hardware kit

A small set of parametric meshes, built once per look and placed by transform. It
is not fitted, because hardware keeps its shape. Positions come from the
`StockingTop.clips` contract.

| Part | Shape | Where |
| --- | --- | --- |
| `clasp` | A U-frame about 12 × 16 mm, with a round rubber button disc 7 mm across behind it | At each clip point on the stocking band, facing out along the band's normal |
| `slider` | A figure-8 adjuster 11 × 7 mm | On each strap, 35% of the way down from the belt |
| `ring` | An O-ring 9 mm across | Optional, where a strap joins the belt on high-waisted belts |

- **Material.** A new finish, `hardware`: metallic matcap and no outline, with
  silver as the default and gold or black as options. It is a separate primitive,
  like the existing opaque trim sections, so a sheer or fishnet stocking never
  makes the hardware see-through.
- **Budget.** At most 12 parts, each under 200 triangles.
- **Skinning.** Each part is bound rigidly (weight 1.0) to the bone its clip point
  is bound to, so it moves with the stocking band and never deforms.

### 2.3 Stocking top options

The `stockingTop` field from HOSIERY_STYLING §4.4 gains `wide`:

| Value | Band | Edge |
| --- | --- | --- |
| `plain` (default) | 3.5 cm opaque, as today | none |
| `wide` | 5 cm opaque | A 2 mm darker rolled edge, as a darker strip in the section's texture |
| `lace` | 5 cm lace mask with an opaque lining | scalloped by the lace texture's own edge |
| `silicone` | 2.5 cm | none |

### 2.4 Denier falloff

Real sheer hosiery looks darker at the sides of the leg, where the eye looks through
more fabric, than down the front. MToon has only additive rim light, so it cannot
darken toward the silhouette at render time. The design bakes a view-independent
approximation into the stocking's alpha instead. The leg's UVs already run round it
from her front (u = 0) to her back (u = 0.5), so alpha can follow u:

```text
alpha(u) = base + (edge - base) * sin²(2πu)       front and back: base; sides: edge
base = opacity from denier (20 den → 0.45),  edge = min(base + 0.25, 0.9)
```

From the front and 3/4 views every preview uses, the sides read darker, as in the
reference. From the side the effect is not view-correct, and the report says the
falloff is baked.

### 2.5 Tinted veil

At 20 denier the reference shows warm skin under a dark veil, not a grey one. The
stocking's base colour gets a small lift toward the body's lit colour where alpha is
low, one texture multiply at build time. Materials are generated per look already,
so this adds no runtime cost.

## 3. Preview rendering upgrade

### 3.1 One renderer for previews and the gallery

Today there are two renderers. The native engine's `preview.webp` comes from the
software rasteriser (`wardrobe/geometry/raster.py`): flat and without MToon. The
gallery's pictures come from `tools/gallery/render.mjs` in Chromium, with the
Studio's own viewer. The reference is the second kind.

The design promotes the gallery renderer into an **optional preview backend**:

```text
WARDROBE_PREVIEW=raster (default, today) | web
```

- `web` renders the look's VRM with `apps/studio/js/viewer.js` in headless
  Chromium, the path `render.mjs` already takes. So a preview matches exactly what
  the Studio and 3D-Avatar-Chatbot show.
- The profile is fixed so previews are comparable: portrait 1086 × 1448, a 3/4 view
  at 35°, the relaxed A-pose, the Studio's key, rim and hemisphere lights, the
  ground shadow, and the `#26232a` background. It frames by the avatar's height.
- Output is `preview.webp` at the profile size, plus `thumb.webp` at 384 × 512. The
  bundle contract gains `thumb.webp` as an optional file.
- If Chromium is unavailable, it falls back to `raster` and says so in the fit
  report, the way the Blender engine falls back to native.

### 3.2 Detail crop

When a look has a `hosiery` block in its fit report, the preview step also writes
`detail.webp`: a 2:1 crop centred between the hem and the stocking tops, taken from
the same render. The frame comes from the hem height and clip positions in the
report, so it is exact rather than guessed from pixels. The Studio shows it beside
the hero, the way the reference shows the straps and clips.

### 3.3 Seated preview

The Judge view's seated toggle (HOSIERY_STYLING §7) uses the same backend with the
`sit` rotations from `POSE_TESTS`, as `preview-sit.webp`. That picture is what
shows a `glimpse` reveal working.

## 4. Which avatar the preview is made on

The reference shows this look on AvatarSample A. It will not be produced on her,
and the design should say so rather than leave it to the gate to discover.

- **Suspender belts and sheer or fishnet stockings are gated.** They are underwear,
  or they show the body. AvatarSample A is an anime-styled character whom nothing
  declares adult, and whose appearance does not settle the question. The gate
  refuses this look on her, and it should. The showcase must not find a way around
  that, for example by composing the preview from 2D layers.
- **The preview for this feature** is made on an avatar the operator has declared
  adult in `assets/library/policy.json`. That can be the calibration mannequin,
  which the verification gallery already uses, or an adult-proportioned avatar
  added to the library with its provenance and licence.
- **On the undeclared library avatars** the Studio offers the look's ungated form:
  the same dress with opaque thigh-high stockings (`denier ≥ 60`, `plain` top) and
  no suspenders. The Check-plan panel explains why the rest is withheld.

## 5. The 2D-overlay alternative, and why not here

A design for a separate project (a 2D talking-avatar renderer) proposed dressing a
source image with warped PNG layers: stockings, bands, straps and belt, plus a
dress mask for occlusion, before lip-sync and motion. For photographs with no 3D
body that is a reasonable approach. For this product it would be a second garment
system, and a weaker one:

| | 3D in the Forge | 2D layer overlay |
| --- | --- | --- |
| Fit | Measured legs and bands, and clips on the fitted band | Hand-set anchors per avatar and pose |
| Occlusion | Real: the dress is fitted outside the belt | A dress mask that has to be segmented or drawn |
| Motion | Skinned, and survives walk and sit | A still image. Motion engines then warp the garment with the body, which is unreliable at the thighs |
| Gate | Enforced before any geometry exists | Needs its own separate enforcement, or bypasses ours |

**Recommendation.** If a 2D renderer needs a dressed source image, it should ask the
Forge for the look's `preview.webp` from the `web` backend, a front view at its
resolution, and use that as its source. That keeps one garment system, one gate, and
one look shown the same way in the Studio, the chatbot and the talking-avatar video.
The change on the renderer's side is one optional input, "source from a Forge look".
That repository is not part of this workspace, so its side is out of scope here.

## 6. Data model additions (optional, additive)

```python
class GarmentFit:                       # template "fit"
    strap_profile: str = "round"        # round | flat
    strap_width_mm: float | None = None
    hardware: str | None = None         # None | silver | gold | black

class StylePlan:
    stocking_top: str = "plain"         # + "wide" (see §2.3)

class Settings:
    wardrobe_preview: str = "raster"    # raster | web
```

The bundle's per-look files add `thumb.webp`, and, for hosiery looks, `detail.webp`
and `preview-sit.webp`. All are optional, and consumers that ignore them are
unaffected.

## 7. Verification

- Every clasp sits within 2 mm of its fitted band. It stays rigid in `walk` and
  `sit`: vertex distances change by less than 0.1 mm.
- Straps: the ribbon's wide face stays within 20° of the thigh surface's tangent
  along its length, and nothing intersects the body or the stocking.
- Hardware is always an opaque separate primitive, even on fishnet.
- Falloff: on the side sectors, alpha is higher than on the front, by the
  configured amount.
- With `web` and a fixed seed, the preview is deterministic: two renders of one look
  are pixel-identical. With Chromium unavailable, the backend falls back to raster,
  and the report says so.
- Non-destructive: under the default `raster` backend, every existing look's
  `preview.webp` and geometry hash are unchanged.
- Gate: the reference look is refused on each undeclared library avatar. Its ungated
  form (§4) is accepted there and passes fit.

## 8. Build order

These phases follow H1–H6 of HOSIERY_STYLING.

| Phase | Delivers | Depends on |
| --- | --- | --- |
| P1 | `web` preview backend, the fixed profile, `thumb.webp` | — |
| P2 | `ribbon` primitive and `strapProfile: flat` | H2 (connector layer) |
| P3 | Hardware kit and the `hardware` finish | H1 (StockingTop), P2 |
| P4 | `stockingTop: wide`, denier falloff, tinted veil | H3 |
| P5 | `detail.webp`, `preview-sit.webp`, Studio display | H4 (reveal), P1 |
| P6 | Reference look in the mannequin verification gallery, and its ungated form in the real-avatar gallery | P1–P5 |
