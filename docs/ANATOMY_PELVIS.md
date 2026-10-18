# The pelvic outlet: a reviewed atlas's surface, fitted to every reference body (AN-A)

The reference bodies ([ANATOMY_REFERENCE](ANATOMY_REFERENCE.md)) are MakeHuman's hm08 template
calibrated to ANSUR II women. Between her thighs the template is an artist's plateau: at the crotch
point a coronal section of every size is flat for about 30 mm. A woman's is a mound between two
folds. A gusset, a thong or a sheer brief fitted there was fitted to nothing real, and every
contact number there measured the plateau.

This is the requirement's seven stages, what each produced and how it is checked. The numbers
come from tools and are regenerated, not written down: `assets/anatomy/pelvic-outlet.json`
(the fit), `assets/anatomy/pelvic-evidence.json` (poses and garments) and
[ANATOMY_VALIDATION](ANATOMY_VALIDATION.md).

## 1. The source: the Human Reference Atlas female skin, CC BY 4.0

Chosen to the requirement *a simple open source reviewed mesh released under CC0 or CC BY*:
the Human Reference Atlas's 3D reference organ *skin of body, female*, v1.5 (HuBMAP; Browne &
Schlehlein 2024, doi [10.48539/HBM453.MVPL.398](https://doi.org/10.48539/HBM453.MVPL.398)), the
outer surface of the NLM Visible Human Female, segmented by the atlas's anatomists. The search
that led to it, the MakeHuman candidates it replaced and its caveats are in
[ANATOMY_ASSETS](ANATOMY_ASSETS.md); the licence and attribution in [LICENSING](LICENSING.md).

`tools/anatomy/import_hra.py` downloads the GLB, refuses any file whose SHA-256 is not the pinned
one, welds it (one closed manifold, 133 350 vertices), finds her midline and crotch point by the
measurer's rule, and keeps the pelvic region: 18 365 vertices, 4.9 mm median edges, in
`assets/anatomy/hra-pelvis.npz`, with `hra-provenance.json` beside it.

![The outlet against the template, median body: front, below in front, below, and a midline slice](images/anatomy/pelvic-shape-ref-f-median.jpg)

## 2. Registered and fitted to the four profiles

`wardrobe.anatomy.pelvis.fit` (run by `tools/anatomy/fit_pelvis.py`, stored per size in
`assets/anatomy/pelvic-outlet.npz`):

1. **scaled** by her trunk's breadth and depth 7 cm above her crotch over the scan's — the scan is
   a broader woman (0.85–0.97 across, 0.97–1.15 front to back);
2. **pitched** about her crotch point to where the scan best agrees with her on a ring 6–13 cm out:
   8–11° on the four sizes, the scan being a body frozen lying on its back;
3. **mirrored and averaged**: the scan is not symmetric and the reference bodies are; taken as it
   is, the fit put a fold on one thigh only;
4. **drawn onto it only where it is the anatomy**: the mound, widening up into the pubic triangle,
   within 7 cm of her crotch point; not behind the start of the perineum and not below the crotch.
   A first fit drew her inner thighs onto the scan's — closer together than a standing body's — and
   made a slit with a wall beside it;
5. **blended**: a Laplacian-regularised non-rigid fit. Where the mask is one the scan decides
   (residual 0.03–0.04 mm); round it her own Laplacian coordinates are kept, so the change fades
   into her over the 14 cm it may touch; beyond that nothing moves.

Her crotch point is the scan's placed on hers, so her calibrated crotch height does not move. The
crotch tape, which runs through the region, is 6–10 mm shorter; thigh girth 6–9 mm larger (the
thigh's top section now includes the folds); everything else moves by under a millimetre. Every
size stays inside its acceptance bound. Each body is still one closed manifold with no
self-intersection. Only vertices move, never topology.

A stored fit carries a hash of the surface it was made on; `pelvis.apply` refuses a fit whose
surface has changed (a recalibration) with a warning to re-run the tool, rather than moving the
vertices of a body it was not fitted to.

## 3. The rig carries it

Topology does not change, so MakeHuman's skin weights — subdivided with the surface — carry the
outlet: the mound moves with her pelvis and, by the 23 % of thigh weight MakeHuman gives it, a
little with each thigh. Binding the mound to her pelvis alone was tried and is worse (314 crossings
seated against 208).

`posecheck.PelvicRegion` counts folds and crossings within 16 cm of her crotch point in each of
`rig.LEG_POSES`, template against outlet:

<!-- POSE TABLE -->

Standing, striding and standing wide nothing crosses. Bent 85° or more at the hip the template's
own groin creases close through themselves under linear blend skinning, and the folds beside the
mound close too: skin pressed on skin, which skinning lets pass. It is hidden inside the closing
fold, not visible from outside, and the tests hold it to `PELVIC_CROSSING_LIMIT`. A pose-driven
corrective, as the shoulders have (SA3), is what would remove it; it is not built.

## 4. The contact body

`ContactBody` is built from whatever surface it is given, so the outlet is in every contact
result. The region `external-genital-region` now holds the mound: it reached 15 mm behind the
crotch point and the mound reaches 33 mm, so its back third was reported as thigh and plain body;
it reaches 35 mm now. The region is named in every clearance report, so a garment's contact there
says it was taken on this approximation.

## 5. Real garments, in poses

`tools/anatomy/pelvic_evidence.py` dresses each reference VRM through the real pipeline — the
reference bodies are declared adult in `assets/calibration/policy.json`, as every gated job
requires — in briefs, a thong, a one-piece swimsuit, a bodysuit, leggings, a mini skirt, sheer
briefs and sheer tights, and measures each against the contact body at rest and with her legs
standing, striding, wide and seated, garment and body each posed by their own skin weights.

**What it found first:** every second-skin garment was bound to her pelvis by the fitter's torso
mask, so when her thighs moved the leg openings did not. Striding, briefs and a thong were 18 mm
inside her; standing wide, 23–25 mm; seated, 40 mm. That is not the outlet — the template body
does the same — and it is not specific to the reference bodies: every avatar's underwear and
swimwear was bound that way.

**The fix** (`wardrobe.providers.templates`, `wardrobe.engines.native`, `wardrobe.vrm.weight_transfer`):
a template that conforms to her below her hips (`conform` ≥ 0.95, `conformBelowHips`) and is not a
dress or a skirt is a *second-skin* garment, and is bound with her own skin's weights everywhere —
the blend of her six nearest skin vertices' weights, as the panel garments already were above her
hips (G5). Dresses and skirts keep their binding: a hem across both legs must not be split between
them. With it, striding and standing wide, briefs and a thong stay about 1 mm clear of her.

<!-- GARMENT TABLE -->

![Garments on the median body, and contact maps](images/anatomy/pelvic-garments-ref-f-median.jpg)

A contact map colours her surface by how far the garment is from it over each point: red inside
her, orange in contact (to 1 mm), yellow close (to 3 mm), green near (to 6 mm), blue a gap (to
15 mm), violet bridging, grey uncovered. A gusset bridges the folds beside the mound and rests on
it; that is what a real gusset does.

Pictures for the other sizes: `images/anatomy/pelvic-shape-<size>.jpg` and
`images/anatomy/pelvic-garments-<size>.jpg`.

## 6. Modelled, approximated, not supported

Stated in `reference.ANATOMY`, carried by every body record, the validation report and every
reference VRM's `extras.wardrobeAnatomy`:

| | |
| --- | --- |
| **Modelled** | the mons pubis, the vulval outer contour as one closed mound, the genitocrural folds beside it, the start of the perineum (from the atlas); the gluteal folds, inguinal creases and inframammary folds (from the template, measured) |
| **Approximated** | the outlet is one woman's surface at about 5 mm, scaled, pitched, mirrored and blended — not a population shape; garments in deep hip flexion are measured against a body whose folds cross under skinning |
| **Not supported** | the labia minora, the clitoral hood, the vestibule, anything finer than 5 mm; nipple and areola beyond the template's surface; soft tissue (the surface is rigid); a corrective for deep hip flexion |

## 7. Gates, licence, provenance

Nothing here changes who may see what. The reference bodies are declared adult in
`assets/calibration/policy.json`, and every garment above that is gated (underwear, swimwear,
sheer) still needs that declaration on the job; the reference VRMs are generated, not committed,
and not offered in the Studio's library. The source is CC BY 4.0: its hash is pinned, its changes
listed, and its attribution is in `docs/LICENSING.md`, in `hra-provenance.json`, in
`pelvic-outlet.json` and in every reference VRM's `extras.wardrobeAnatomy.attribution`.

## Regenerating

```bash
python tools/anatomy/import_hra.py                  # the atlas region (downloads the pinned GLB)
python tools/anatomy/fit_pelvis.py                  # every size, a minute or two each
python tools/anatomy/validate_reference.py          # the validation report
python tools/anatomy/pelvic_evidence.py OUT --publish
pytest tests/unit/test_pelvic_outlet.py tests/integration/test_second_skin_binding.py
```
