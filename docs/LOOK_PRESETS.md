# Look presets (P1)

Named looks of more than one garment, in `wardrobe/pipeline/look_presets.py`.
Like the hosiery presets, a look preset is shorthand for a request someone could
type: it fills the prompt when the prompt *is* the preset's name, fills a block
the request left empty, and grants nothing. Every garment is planned, fitted and
gated exactly as if typed.

```json
{"outfit": {"prompt": "corset_top_low_rise_mini", "preset": "corset_top_low_rise_mini"}}
{"outfit": {"prompt": "visible_thong_low_rise_jeans", "preset": "visible_thong_low_rise_jeans",
            "visibleThong": {"style": "classic"}}}
```

`GET /v1/vocabulary` lists them under `lookPresets`.

## `corset_top_low_rise_mini` — lingerie-as-outerwear, no declaration needed

A black **corset top** (`top-corset-v1`, new) over a black **low-rise pleated
mini**. Both are clothes, so any avatar can wear it.

- **Corset** (`procedural:corset`): fitted from the bust to her natural waist —
  the crop top it borrows from stopped at the underbust — with a sweetheart
  neckline, a hem dropping 3.5 cm (at 1.6 m) to a point at centre front, shoulder
  straps, and boning channels drawn as a shaded texture every 4.5 cm, the route
  knife pleats use. "corset", "corset top", "bustier" name it; the lingerie
  foundations keep their own words (guêpière, waspie), and a lace or sheer corset
  is still gated by its material.
- **Low-rise skirt**: `rise` ("low-rise", "ultra-low") now moves a skirt's top
  too, 35% / 50% of the way from her waist to her hips. A skirt without the word
  starts at her waist exactly as before.
- **Liner**: under a low-rise skirt the slip-shorts liner is cut lower still,
  so its band never shows above the skirt's.

![corset top + low-rise mini on the calibration mannequin](images/looks/corset-mini.webp)

## `visible_thong_low_rise_jeans` — the Y2K "whale tail", underwear, gated

A white fitted crop top, blue **low-rise** straight jeans and a black **tailored
V-string** whose side straps and back V sit above the jeans' waistband. It is two
garments placed against each other, so the `visibleThong` block moves exactly
two waistlines — the thong's up, the jeans' down — and nothing else.

| `style` | thong rise | jeans | strap above waistband* |
| --- | --- | --- | --- |
| `subtle` | 0.86 | low | 2.1 cm |
| `classic` | 1.05 | low | 5.1 cm |
| `full` | 0.98 | ultra-low | 9.2 cm |

\* measured on the calibration mannequin through the pipeline. `thongRise`
(0.2–1.15, a fraction of her crotch → waist span) and `jeansRise`
(`low` / `ultra-low`) set either side directly and win over the style.

**It is underwear.** An avatar without an adult declaration is refused, with
Forge's usual reason, exactly as for any underwear; no preset, block or style
changes that. The pictures below use the calibration mannequin, which
`assets/calibration/policy.json` declares adult.

![visible thong over low-rise jeans, three styles](images/looks/visible-thong.webp)

### `visible_thong_cami_baggy_jeans`

The same whale tail with a plain white **cropped cami** on thin straps
(`top-cropped-cami-v1`, new, opt-in — chosen only when named, so "crop cami"
still plans the lace one), **low-rise baggy jeans** and a **white** tailored
V-string, `classic` by default (5.1 cm of strap on the mannequin). Gated the same
way.

The preview below dresses the same declared mannequin with its skin tinted a
warmer tone, only so white fabric reads against it; the body and its declaration
are unchanged.

![visible thong with a white cropped cami and baggy low-rise jeans](images/looks/visible-thong-cami.webp)

## What changed underneath, and what did not

- `StylePlan.brief_rise` places a pattern-block brief's waistline. Only the
  `visibleThong` block sets it; every other brief is drafted as its template says.
- Trousers gain `ultra-low`; a yoke never drops within 6 cm of her crotch.
- Against the gallery hash baseline all 81 existing looks are byte-identical.
