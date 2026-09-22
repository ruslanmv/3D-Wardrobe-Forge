# Calibration bodies

The reference body shapes the fitting stage is tuned against, defined in
`wardrobe/vrm/build.py:CALIBRATION_BODIES`.

| Id | Height | Shoulders | Hips | Why it exists |
| --- | --- | --- | --- | --- |
| `calibration-a-petite` | 1.48 m | 0.29 m | 0.28 m | short limbs, narrow frame |
| `calibration-b-medium` | 1.62 m | 0.34 m | 0.32 m | the middle of the range |
| `calibration-c-tall` | 1.83 m | 0.42 m | 0.34 m | long limbs, high hip line |
| `calibration-d-broad` | 1.70 m | 0.46 m | 0.44 m | wide frame, short legs |

They are **parameters, not files**: nothing binary is stored here. Materialise
them whenever you need them:

```bash
wardrobe-forge fixtures --out assets/fixtures
```

## Why these four

M2 — "the same garment fits several different avatars automatically" — is the
milestone that cannot be skipped. Proving it needs bodies that genuinely
differ, so this set spans 1.48–1.83 m in height with hip widths varying by more
than 1.5×, and mixes long-legged with short-legged at similar heights.

`tests/unit/test_measure.py::test_bodies_are_distinguishable` enforces the
spread, so the acceptance matrix cannot quietly degrade into four copies of the
same avatar.

## Adding one

Append a `BodyProportions` entry to `CALIBRATION_BODIES`. Every parametrised
test and the full acceptance matrix pick it up automatically — which is the
point: a new body shape immediately becomes a requirement, not an option.
