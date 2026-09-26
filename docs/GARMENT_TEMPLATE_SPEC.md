# Garment template specification

A template is **metadata first, geometry second**. The metadata is what lets a
handful of robust garments cover hundreds of prompts.

Templates live in `assets/garment_templates/<category>/<id>.json` and are
loaded by `TemplateCatalog.from_directory`.

## Schema

```json
{
  "schemaVersion": 1,
  "id": "dress-a-line-v1",
  "name": "A-line dress",
  "category": "dress",
  "mesh": "procedural:dress",

  "coverage": ["chest", "waist", "hips", "upperLegs"],
  "anchors":  ["chest", "waist", "hips", "upperLegs"],

  "silhouette": "a-line",
  "hem": "knee",
  "sleeve": "none",

  "fit": {
    "bodyClearanceMm": 6,
    "allowLengthScale": true,
    "allowWidthScale": true,
    "minLengthScale": 0.7,
    "maxLengthScale": 1.3
  },

  "materials": {
    "supportsBaseColor": true,
    "supportsPattern": true,
    "supportsMetallic": false
  },

  "tags": ["dress", "a-line", "casual", "formal", "everyday"],
  "description": "Fitted bodice flaring from the waist."
}
```

## `coverage` vs `anchors` — the important distinction

These look similar and are not the same thing.

- **`coverage`** — what the garment *hides*. Drives body masking and the
  coverage figures in the fit report.
- **`anchors`** — what the garment *binds to*. Drives skin weights.

They differ whenever a garment hangs past the joints it should follow. A
floor-length column gown **covers** the shins but must **not be anchored** to
them: binding a long hem to the lower legs tears it apart the moment the legs
swing in opposite directions. Real long skirts hang from the pelvis, so:

```json
"coverage": ["chest", "waist", "hips", "upperLegs", "lowerLegs"],
"anchors":  ["chest", "waist", "hips", "upperLegs"]
```

`tests/unit/test_templates.py` enforces this for every floor- and ankle-length
template.

## Field reference

| Field | Values | Notes |
| --- | --- | --- |
| `category` | `dress` `skirt` `top` `trousers` `jacket` `shoes` | selects the builder |
| `mesh` | `procedural:<kind>` or a GLB filename | procedural shells are generated at the avatar's measurements |
| `coverage` / `anchors` | `neck` `shoulders` `chest` `waist` `hips` `upperArms` `lowerArms` `upperLegs` `lowerLegs` `feet` | |
| `silhouette` | `a-line` `fit-and-flare` `cocktail` `sheath` `pencil` `ball-gown` `straight` `wide` `slim` `oversized` | modulates flare and length |
| `hem` | `mini` `knee` `midi` `ankle` `floor` | fraction of hip→ankle distance |
| `sleeve` | `none` `short` `long` | swept along the arm bone chain |
| `fit.hemFlareRatio` | 0.85–2.5 | skirts: hem half-width over her full hip; absent, the silhouette's default |
| `fit.flareStart` | `waist` `high-hip` `hip` `below-hip` | skirts: where the fitted part ends and the flare begins |
| `fit.flarePower` | 0.5–4 | skirts: flare profile, `progress ** power`. Above 1 is a slow A-line; below 1 is a skater's early curve |
| `fit.waistEaseMm` / `fit.hipEaseMm` | mm | skirts: ease over her measured outline at the waist and at the full hip |
| `fit.pleats` / `fit.pleatDepth` | count / metres | zero-mean pleats, clamped to body + clearance |
| `fit.drapeFolds` / `fit.hemDrape` | 0–24 / 0–0.08 | a soft zero-mean hem drape; both must be set |
| `fit.bodyClearanceMm` | 0–40 | fabric-to-body spacing; 5–8 fitted, 12–18 outerwear |
| `materials.supportsMetallic` | bool | when false, a "metallic" prompt is ignored for this template |
| `tags` | free text | matched against the prompt during selection |
| `defaultForCategory` | bool | the category's answer to a prompt that names nothing else ("skirt", "navy skirt", the Studio's "Planner chooses"); exactly one per category with a choice, never an opt-in template |

## How a template is chosen

`score_template` in `wardrobe/pipeline/plan_outfit.py`:

```
+10  category matches
 +4  silhouette matches
 +2  hem matches
+1.5 sleeve matches
+1.0 per tag found in the prompt
+1.5 formality register matches a tag
```

A prompt that names the category and nothing else — no silhouette, hem, sleeve,
formality, template tag or template name; a colour or a fabric does not count —
skips scoring and gets the category's `defaultForCategory` template. Scoring
cannot answer it: "skirt" scores the A-line, maxi and pencil skirts the same,
and that tie used to fall to the template id sorted backwards, so every bare
"skirt" was the pencil, a knee-length tube, chosen by its file name.

Ties among scored templates still break on `id`, so selection is deterministic.
The default is deliberately not a tie-break there: "slip shorts" ties the
Denim Shorts' generic `shorts` tag, and preferring the default would put her in
denim. Renaming a template cannot change what a bare category gets —
`tests/unit/test_planner.py` renames the pencil skirt both ways to prove it.

| Category | Default |
| --- | --- |
| skirt | `skirt-a-line-v1` |
| dress | `dress-a-line-v1` |
| top | `top-tee-v1` |
| trousers | `trousers-straight-v1` |
| jacket | `jacket-blazer-v1` |
| shorts | `shorts-denim-v1` |
| nightwear | `night-nightgown-v1` |
| shoes | `shoes-flats-v1` |
| legwear | `legwear-tights-v1` |
| swimwear | `swim-one-piece-v1` (still behind the adult gate) |
| underwear | `under-briefs-v1` (still behind the adult gate) |

Every procedural skirt (`procedural:skirt`) is given a waistband after fitting
(`wardrobe/geometry/waistband.py`): its top rows, 3 mm proud, drawn a shade
darker as a second primitive. It is built from the fitted shell rather than
beside it because fitting would press it back into the skirt.

## Adding a garment

1. Drop a JSON file in the right category folder.
2. `make templates` — lists and validates the library.
3. `pytest tests/unit/test_templates.py` — schema, coverage regions, anchor
   resolvability, clearance sanity, the floor-length rule.
4. Only if you need a *new shape* (not a new look): add a builder in
   `wardrobe/geometry/procedural.py`.

Most new garments are step 1 alone.

## Binary mesh templates

`"mesh": "dress.glb"` points at a GLB beside the JSON. That path requires the
Blender engine, which deforms the authored mesh onto the body. The shipped
library is entirely procedural so the repository carries no binary assets and
the whole library works on the native engine.
