# Garment templates

One JSON file per garment, grouped by category. Loaded by
`TemplateCatalog.from_directory` and served at `GET /v1/templates`.

```
dresses/   a-line · evening column · cocktail · long-sleeved wrap
tops/      tee · blouse · camisole
skirts/    a-line · pencil · maxi
trousers/  straight · slim jeans · wide-leg
jackets/   tailored blazer · oversized coat
shoes/     flats · ankle boots
```

Every shipped template is **procedural** (`"mesh": "procedural:<category>"`):
the shell is generated at each avatar's own measurements rather than deformed
from an authored mesh. That keeps the repository free of binary assets and lets
the whole library work on the native engine.

A template's `coverage` (what it hides) and `anchors` (what it binds to) are
deliberately separate — a floor-length gown covers the shins but must hang from
the hips. The full schema and that distinction are documented in
[`docs/GARMENT_TEMPLATE_SPEC.md`](../../docs/GARMENT_TEMPLATE_SPEC.md).

## Adding one

1. Copy a nearby JSON file and edit it.
2. `make templates` — lists and validates the library.
3. `pytest tests/unit/test_templates.py`.

Adding a *new shape* (rather than a new look) also needs a builder in
`wardrobe/geometry/procedural.py`. Most new garments do not.
