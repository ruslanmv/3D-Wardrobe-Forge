# Hosiery upgrade: the complete plan

**Status: built. See [HOSIERY](HOSIERY.md) for what ships and §11 there for where it departs from this design.** This document ties together
[HOSIERY_STYLING](HOSIERY_STYLING.md) (the garments and the reveal control) and
[HOSIERY_PREVIEW](HOSIERY_PREVIEW.md) (assets and rendering) into one upgrade. It
analyses the 2D compositor `garter_belt.py`, written for the separate
`avatar-renderer-mcp` project, and takes what is useful from it. It also defines
how that project consumes the Forge's output. Everything is additive: an outfit
without hosiery takes exactly today's path.

## 1. Analysis of `garter_belt.py`

### What it is

It is a deterministic OpenCV compositor for a single still image. It finds hip,
knee and ankle anchors, from MediaPipe Pose, from explicit anchors, or from a fixed
fallback for a centred portrait. It then paints, in order: a translucent stocking
polygon per leg, an opaque band, the belt (only in `full` mode), a straight line
per strap, and a capsule and dot per clip. An optional mask restores the original
dress on top. The result is a new source image for the talking-avatar engines.

### What it gets right, and the Forge adopts

| Idea in the file | Adopted as |
| --- | --- |
| `visibility: straps_only \| full`: belt hidden under the dress, only strap ends and bands show | The `reveal` levels. `statement` with an outer layer is `straps_only`; with no outer layer the belt shows, which is `full`. In 3D, occlusion comes from layer order, not a mask |
| `stocking_top_t = 0.34` of hip → knee, `hem_t = 0.18` | The default solution the reveal solver must reproduce for `statement` on the calibration bodies: hem 18%, band 34% of the thigh |
| `front_straps_per_leg: 1 \| 2` | `suspenders: 4 \| 6`: one front and one back strap per leg, or two front and one back |
| Colour defaults: belt `#111111`, clips `#C7C9CC` | The default belt colour and the `hardware: silver` colour |
| `stocking_alpha 0.43`, `band_alpha 0.88` | Calibrates the denier map: 20 den gives a base alpha of 0.45, and the `wide` band is opaque |
| Band height 0.22 × hip span, strap width 0.055 × hip span | Cross-checks the 5 cm `wide` band and the 9 mm ribbon on a 0.23 m hip span |
| Validation up front (anchor ordering, plausible hip span, option ranges) | The same stance for the new fields: out-of-range values are refused when the request is made |
| Deterministic output for known avatars | Deterministic previews from the `web` backend (HOSIERY_PREVIEW §3) |

### Where it falls short

Most of these limits come from being 2D. The rest are defects.

| # | Finding | Consequence |
| --- | --- | --- |
| F1 | Leg widths are ratios of the hip span, with no leg mask (`segmentation.py` is planned but not used) | The stocking tint spills onto the background beside slim legs, and leaves bare edges on full ones |
| F2 | `cv2.fillConvexPoly` on a six-point leg outline | The outline stops being convex when the knee bends (sitting, walking), and the fill is wrong |
| F3 | Stockings are painted over everything below the hip line | Hands beside the thighs, as in an A-pose, and shoes get tinted unless a mask is supplied |
| F4 | Straps are straight 2D lines from a synthetic point near the hip | No curvature over the thigh, no slack, and no way to check tension |
| F5 | Uniform sheer alpha | No darker edges, no skin through the veil: the flat grey look HOSIERY_PREVIEW §2.4–2.5 avoids |
| F6 | The fallback anchors are fixed (hips at 42.5% of image height) | Correct for one framing only. The reference image's hips are elsewhere |
| F7 | The module is built by string-patching its own source (`code.replace(...)`) before writing it | A fragile build step. The hem fix only applies if the patched text matches exactly. Ship the module as source |
| F8 | A still image is dressed, then handed to motion engines | FOMM-style warping moves the painted garment with the pixels, not the body, so it smears at the thighs in motion |
| F9 | **No gate** | It will dress any image: an avatar that is not declared adult, or a photograph of a real person. See §2 |

**Verdict.** It is a sound prototype for adding hosiery to a flat image, and a useful
source of defaults. It should not be how this product makes the look. In 3D the
Forge already has what the compositor approximates: real legs, real occlusion,
skinning for motion, and the gate.

## 2. Safety rules

These hold in both repositories.

1. **Hosiery with suspenders, and sheer or fishnet stockings, is gated** as
   intimate wear. It needs the model's terms to allow it and the operator's adult
   declaration. A prompt, a request field or a preset cannot supply either.
2. **Never on photographs of real people.** Adding lingerie to a photo of a real,
   identifiable person, the "auto" mode proposed for arbitrary uploads, produces
   intimate imagery of someone who has not agreed to it. Neither repository offers
   it. The 2D path in `avatar-renderer-mcp` accepts only a Forge-rendered source,
   whose gate has already run, or a synthetic avatar the operator declares adult.
   Uploaded photographs get no intimate wardrobe.
3. **Never on an undeclared avatar.** That includes the library's anime-styled
   avatars. Their ungated alternative is opaque thigh-highs without suspenders
   (HOSIERY_PREVIEW §4).
4. **No anatomy.** Garments are built on the authored body. Nothing adds or
   reconstructs body detail.

## 3. The upgrade, end to end

```text
                   ┌────────────────────── 3D Wardrobe Forge ──────────────────────┐
request ─► gate ─► plan (belt, stockings, connector, outer, reveal)
                   │
                   ├─ foundation: suspender belt / waspie / guêpière ─┐
                   ├─ legwear: stockings ─► publishes StockingTop     │ measured body
                   ├─ connector: ribbon straps + hardware ─► tension in walk and sit
                   ├─ outer: dress or skirt, hem solved for reveal    │
                   └─ validate ─► hosiery report ─► look.vrm
                                                  │
                                    web preview backend (Studio viewer)
                                    preview.webp · thumb.webp · detail.webp · preview-sit.webp
                   └───────────────────────────────┬───────────────────────────────┘
                                                   │  "source from a Forge look"
                   ┌───────────────────── avatar-renderer-mcp ─────────────────────┐
                   │ source image = Forge preview (front view, requested size)     │
                   │ ─► existing render(): Wav2Lip / MuseTalk / FOMM / …           │
                   └───────────────────────────────────────────────────────────────┘
```

### 3.1 In the Forge

These are the components specified in the two parent documents, in build order:

| Phase | Component | Spec |
| --- | --- | --- |
| H1 | `StockingTop` contract: clips on the fitted band | STYLING §4.1 |
| H2 | `suspender-belt` kind, connector layer, `briefsOver`, strap rest length and tension | STYLING §4.2 |
| P2 | `ribbon` primitive, `strapProfile: flat` | PREVIEW §2.1 |
| P3 | Hardware kit and the `hardware` finish | PREVIEW §2.2 |
| H3 + P4 | `seam`, `stockingTop` (plain, wide, lace, silicone), `denier`, falloff, tinted veil | STYLING §4.4, PREVIEW §2.3–2.5 |
| H4 | `reveal` solving in the `POSE_TESTS` poses, and the hosiery report | STYLING §4.3 |
| H5 | High-waisted belt, waspie and guêpière templates | STYLING §4.5 |
| P1 + P5 | `web` preview backend, thumb, detail and seated renders | PREVIEW §3 |
| H6 + P6 | Studio controls, `setId`, ensembles, gallery additions | STYLING §7, PREVIEW §8 |

### 3.2 In `avatar-renderer-mcp` (a separate repository, not built here)

That repository is not in this workspace. The contract is kept minimal so its side
is small:

```json
{
  "avatarPath": "avatar.png",
  "audioPath": "speech.wav",
  "source": {
    "forgeLook": {
      "baseUrl": "https://forge.example",
      "lookId": "look_…",
      "view": "front",
      "size": [1086, 1448]
    }
  }
}
```

- When `source.forgeLook` is present, the renderer fetches
  `GET /v1/looks/{lookId}/preview?view=front&w=1086&h=1448` from the Forge and uses
  it in place of `avatarPath`. The Forge endpoint is new, and renders with the `web`
  backend. The Forge has already gated the look when it was made, so the renderer
  adds no wardrobe logic of its own.
- The renderer's own `garter_belt.py` compositor, if kept at all, is limited by §2:
  synthetic avatars the operator declares adult, never uploaded photographs. It is
  also marked as the fallback for a deployment with no Forge.
- Everything after the source image, the lip-sync and motion engines, is unchanged.

## 4. The feature picture

`docs/images/features.webp` is the README's feature map: twelve cards. Nine show
the product on the real library avatars, using renders from the gallery. Three are
text, for properties a picture cannot show: validation, licensing and safety,
plain Python. The twelfth card is this upgrade, marked **Designed · not yet built**,
and illustrated with a line diagram of the layers (belt, hem, clips, band,
stocking), not with a render. That keeps the picture honest about what ships, and
keeps the gated look off the undeclared avatars. `tools/gallery/showcase.py`
generates it, so it is regenerated with the rest of the gallery. When the upgrade
is built, its card switches to a render made on an adult-declared avatar.

## 5. Acceptance criteria for the upgrade as a whole

- The five looks of the styling brief complete and pass fit on every calibration
  body, in both VRM specs, with the operator's declaration. Each is refused on
  every undeclared library avatar.
- Clips sit within 2 mm of the fitted band, and strap elongation is ≤ 10% in
  `walk` and `sit`.
- The reveal level achieved equals the level requested whenever the length is not
  given explicitly.
- Previews from the `web` backend are pixel-deterministic, and fall back to raster
  with a note.
- **Non-destructive:** the 81 existing gallery looks keep identical geometry
  hashes, and all existing tests pass unchanged.
- **Cross-repository:** a `forgeLook` source renders through every engine in
  `avatar-renderer-mcp` with no wardrobe code of its own. Verified in that
  repository when it is built.
