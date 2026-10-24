# Lingerie pattern engine: how a garment is made, and where to change it

For an agent adding or improving a lingerie construction. Read
`LINGERIE_REFERENCE_LIBRARY.md` for the data, `LINGERIE_FABRIC_PHYSICS.md` for
materials, `LINGERIE_VALIDATION.md` for how a change is proved.

## The pipeline, as it runs today

```
template JSON (assets/garment_templates/underwear/*.json, schemaVersion 2, "lingerie" block)
  -> wardrobe.lingerie.specs.parse_block        BriefSpec / BraSpec / BodysuitSpec / StrapBlock
  -> wardrobe.lingerie.blocks.build_block       landmarks -> BodyFrame -> 3D panels drafted on her
       references.uma_gusset (opt-in)           figures drafted from a verified reference (RL4)
  -> shell fit (wardrobe.engines.shell)         radial passes; gusset left for:
  -> wardrobe.lingerie.fit.after_shell          gusset seated between fitted seams (GF1 keeps its cut width)
  -> wardrobe.vrm.weight_transfer               her skin's weights; second-skin smoothing (PF2)
  -> wardrobe.lingerie.atelier.embellish        lace bands, binding, hardware
  -> wardrobe.lingerie.report                   elastic tension, rules, references -> fit report "lingerie"
```

Panels are drafted **directly in 3D on her measured frame** (`BodyFrame.point(phi, y)`), not
cut flat and sewn: there is no 2D panel or seam graph to simulate. That is the largest
structural difference from GarmentCode-style engines, and the reason a flat reference
pattern (BraCupPattern's cup outline) cannot simply be dropped in.

## The conceptual grammar, mapped to code

| Component | Where it lives | Status |
| --- | --- | --- |
| FrontPanel / BackPanel | `blocks/brief.py build_brief` (columns round her, leg line solved for coverage) | exists |
| Gusset | `blocks/brief.py gusset_point`; seated by `fit.seat_gusset` | exists; width from spec or Uma (RL4) |
| LegOpening | `brief.py leg_line`, `legCutHeight`, `legExtensionMm` | exists |
| WaistElastic, leg elastic | `elastic.py ELASTICS` (force curves), measured per pose | exists, class-typical curves |
| BraCup | `blocks/bra.py build_bra` (`cupHeight`, `cupInner`, `cupOuter`, ease) | exists, scalar cups |
| CentreGore | `BraSpec.gore_height_mm`, `gore_width_mm` | exists |
| Underband, SideWing | `BraSpec.underband_width_mm`, `wing_height_mm` | exists |
| ShoulderStrap | `straps.py route`, `build_ribbon_strap`, `StrapBlock` | exists |
| Closure | `BraSpec.closure` (`back`, `front`, `none`) | named only (no hardware geometry) |
| LaceTrim, Binding | `atelier.py`, `fabrics.py galloon` | exists (visual) |
| Suspender | `wardrobe/hosiery/garter_belt.py`, `suspender_straps` | exists |
| DecorativeHardware | `atelier._strap_hardware`, `hosiery/hardware.py` | exists |
| CupSeam, Underwire, Cradle, BoningChannel | — | **missing**: no module models them |

## Adding a field to a block

1. Add it to the spec dataclass in `wardrobe/lingerie/specs.py` with a default that
   reproduces today's garment, and validate its range in `__post_init__` (a typo then fails
   `TemplateCatalog` validation, not silently builds a default).
2. Use it in the block (`blocks/*.py`). If it replaces a constant on some templates only,
   make it opt-in: the 35 catalogue pieces are pinned by
   `assets/catalog/adult/underwear-audit.json` and must not move unless that is the change.
3. If fitting re-derives the spec (`fit._seat_brief_gusset` re-parses the template), carry
   the drafted value through — RL4 had to: the seat first used the template's 55 mm gusset
   instead of the width the block had drafted.

## Drafting from a reference (RL4)

```json
"lingerie": {"block": "brief", "fabric": "stretch-knit",
             "brief": {"preset": "classic", "gussetDraft": "freesewing-uma"}}
```

`gussetDraft: "freesewing-uma"` replaces the gusset width with Uma's rule on her measured
body, and the fabric's stretch allowance (from `materials/fabrics.json`, or Uma's default
when the fabric has none). The fit report's lingerie piece then carries
`references: [{draft, gussetWidthMm, gussetLengthMm, appliedTo, inputs, provenance}]`, each
input marked `body`, `reference` or `material`. Proved by
`tests/integration/test_reference_gusset.py` on two reference bodies.

**Known limit.** The gusset's length is not a parameter of this block's geometry: it runs
between seams fixed `SEAM_ABOVE_CROTCH_M` above her crotch, front and back. Uma's length
(94 mm on VRoid Female, against the 150 mm constant) is recorded and applied to the texture
only. Making seam heights draftable is the next step to apply it.

## Generating a new design

1. Inspect the catalogue first: `ls assets/garment_templates/underwear/` and
   `docs/UNDERWEAR_AUDIT.md` (an equivalent may exist under another name).
2. Write the template (copy the nearest `*-v2.json`); give it a new id and distinct tags.
3. Validate: `python -m pytest tests/unit -k template -q`.
4. Fit and measure it: `python tools/catalog/underwear_audit.py --out /tmp/ua --only <id>`.
5. Render it: `python tools/catalog/render_templates.py --profile underwear --avatar fem-vroid`
   (fem-vroid must be fetched: `make library`).
6. Pose QA: `python tools/inspect/fit_look.py --template <id> ... --out /tmp/x.vrm`, then
   `tools/inspect/pose_contact.py` (see `docs/POSE_CONTACT_QA.md`).
