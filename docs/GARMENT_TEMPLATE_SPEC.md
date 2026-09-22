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
| `fit.bodyClearanceMm` | 0–40 | fabric-to-body spacing; 5–8 fitted, 12–18 outerwear |
| `materials.supportsMetallic` | bool | when false, a "metallic" prompt is ignored for this template |
| `tags` | free text | matched against the prompt during selection |

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

Ties break on `id`, so selection is deterministic.

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
