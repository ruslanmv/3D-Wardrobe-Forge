# Bare production readiness: eligibility, skin verdict, readiness, reconstruction

2026-11-15, Forge `ultimate`. Batches BE1 (eligibility contract), SR2 (skin verdict), BE2
(readiness report) and BR1 (opt-in reconstruction, M6).

## BE1. One eligibility contract for bare

**Defect fixed.** `bare_body.prepare` called the body-surface gate with three of its questions
(model terms, operator switch, adult declaration) and never the fourth: it passed neither
`intimate` nor a design review, while `prepare_body_surface` passes both for an intimate region.
A bare body shows everything a garment covered, so a library character with an empty review
registry could be built bare on a declaration alone.

`wardrobe/body_surface/eligibility.py: assess()` now answers five questions and reports every
answer, not only the first refusal:

| Check | Owner | Source |
|---|---|---|
| `author-permission` | the model's author | the VRM's own terms, read strictly |
| `operator-switch` | the deployment | `WARDROBE_ADULT_BODY_SURFACE` (off by default) |
| `adult-declaration` | the operator | `avatar.depictsAdult` (server-side for the library) |
| `design-clearance` | a person, or Forge itself for its own bodies | SHA-256 of the exact source bytes |
| `private-session` | the server | `options.private` (forced for bare by the library route) |

Body integrity is measured after removal and reported in the same `baseBody` block.

`design-clearance` passes for exactly two things, both keyed by the source file's SHA-256, so a
changed file is covered by neither:

- a person's review with `outcome: "clearly-adult"`, reviewer, date and evidence in
  `assets/body_surface/adult-design-reviews.json` (unchanged schema, still empty);
- a **synthetic-reference** record in `assets/calibration/synthetic-references.json`, written by
  `tools/anatomy/register_synthetic_references.py`, which rebuilds each reference body Forge
  generates (MakeHuman CC0 adult template calibrated to ANSUR II women aged 21+, faceless, no
  hair), hashes the bytes and records the provenance. It registers only bodies the operator's
  `assets/calibration/policy.json` declares adult. It is reported as `kind: synthetic-reference`,
  never as a review. `--check` rebuilds and fails if the bytes are no longer reproduced.

A test asserts the synthetic registry never holds a library character's hash, and the review
registry never holds a test fixture. Tests that need a clearance use
`tests/conftest.py: clear_design_for_test`, which writes a temporary registry copy with the
reviewer named `test-fixture (not a review)`.

## SR2. Model Girl's `skinRestored: false`

Measured on her undressed body texture (2048², body region 3.18 M texels): **0 painted texels,
0 cut-away texels**, furthest texel 42.3 from her skin colour (threshold 45). AvatarSample B, for
contrast, has 1.07 M painted texels. Cause **A**: nothing needed restoring. The defect was the
report: `restore_skin` returns None both for "nothing to restore" and "could not look", and the
report read it as a failure.

`skin_census()` measures the region without changing anything; `restoration_verdict()` names the
result from the census *after* restoration:

- `restoration-completed`: restoration ran and left 0 painted / 0 cut-away texels;
- `restoration-not-needed`: nothing ran, and the region has none;
- `unverified`: no skin found, protected anatomy, or texels left.

Library result: A, B, C, VRoid F/M and Rinna `restoration-completed`; Model Girl
`restoration-not-needed`; O not reached (refused for geometry).

## BE2. Readiness per character

`python tools/audit/bare_readiness.py --md docs/qa/BARE_READINESS.md` reads every library avatar,
checks the file hash against the manifest, answers the four concerns from their owners, runs the
geometry and texture checks (nothing stored or rendered), and prints the plan-only prebuild
request and command. Result today: seven `awaiting-design-review`, O `blocked-geometry`. See
`BARE_READINESS.md`.

## BR1 (M6). Opt-in reconstruction

`options.bodyCompletion: "proxy"` (only with `baseBody: bare`) fills only the bands an authored
body lacks with BC1's featureless patch, shaped from the garment that covered the hole. It needs
its own operator switch `WARDROBE_BARE_BODY_COMPLETION` (off by default; the adult switch does
not imply it), and all five eligibility checks. Unset (the default) keeps bare authored-only
and refuses an incomplete body exactly as before.

A reconstructed look:

- is tagged in the file: `wardrobeForge.reconstructed: true`, `reconstruction: "bc1-proxy"`,
  `reconstructedRegions`; the patch is one mesh of its own tagged `bodyProxy`;
- keeps every authored accessor byte-identical (the same fingerprint check as authored-only);
- is private, and **is never registered** in any prebuilt list, so no app can serve it.

AvatarSample_O: authored-only refused (`body-incomplete-for-bare`); with completion, `upper`
filled, integrity complete, not registered (test). Serving a reconstructed body to the app
would need a review of the *output* file; that registry does not exist and was not invented.

## Tests

`tests/unit/test_bare_eligibility.py`, `tests/unit/test_skin_census.py`, the BE1 and BR1 cases
in `tests/integration/test_bare_body.py`. The byte-for-byte reproduction of `ref-f-median` is
marked `slow`.

## BE3. The bare prebuild planner

`tools/prebuild.py --only body-bare-v1` planned 0 looks against a real Forge (the garment
catalogue leaves body modes out). It now plans one pair per library character without that
listing. Verified against a local Forge with the switch on: 4 planned, 4 refused at
`design-clearance` (`body_surface_not_permitted`), 0 built.

## Behaviour change to know about

Before BE1, committed Forge built a bare look for a library character on the operator's
declaration alone. From BE1 it also needs a design clearance for the exact file. The review
registry is empty, so no library character builds bare until a person records a review.

## BR2. AvatarSample_O: what is missing, and a patch that meets her properly

2026-11-16, Forge `ultimate` at `95a64bf`.

### Eligibility today (real `eligibility.assess`, file `e5c0395b59b6…`)

| Check | Answer | Who acts |
|---|---|---|
| `author-permission` | yes (the file allows modification and redistribution) | nobody |
| `operator-switch` | no (`WARDROBE_ADULT_BODY_SURFACE` off; on only on a local build command) | operator |
| `adult-declaration` | yes (`policy.json`, a declaration and not a review) | nobody |
| `design-clearance` | **no**: `adult-design-reviews.json` holds no entry for this hash | independent reviewer |
| `private-session` | yes (forced by the library route) | nobody |

No bare O was built: the design clearance is missing, and nothing here supplies one.

### Her chest, measured (case C: both)

`skin_restore.py` said her chest skin is there as geometry with alpha cutting it away; the
readiness report said the mid-chest band is missing. Measured on the source file with her
garments taken out of the count (nothing stored or rendered):

| Band | Span (m) | Coverage per band (6) | Skin area (cm²) | Open boundary (mm) | Region texels | Cut-away texels | Painted texels |
|---|---|---|---|---|---|---|---|
| upper | 0.881–1.213 | 1, 1, **0**, **0.25**, 1, 1 | 1805 (1718 solid) | **2011** (153 edges) | 215 655 | **9 221** | 210 |
| lower | 0.797–0.881 | all 1 | 548 | 0 | 35 594 | 0 | 12 101 |
| left thigh | 0.464–0.787 | 1 … 0.94 | 975 | 0 | 50 898 | 0 | 1 800 |
| right thigh | 0.464–0.787 | 1 … 0.94 | 975 | 0 | 50 905 | 0 | 4 260 |
| left shin | 0.087–0.464 | all 1 | 802 | 0 | 74 608 | 0 | 0 |
| right shin | 0.087–0.464 | all 1 | 802 | 0 | 74 609 | 0 | 0 |

- **Absent triangles** (B): from 0.964 m to 1.075 m there is no skin triangle in any of the 16
  directions round her; 1.075–1.102 m has 4 of 16; 1.102–1.130 m is open at the back (6 of 16).
  No texture can fill that.
- **Alpha-cut skin** (A): 88 skin triangles (87 cm²) on the rim of that hole, just below it
  (0.95–1.00 m) and just above it (1.05–1.20 m), are geometry cut away by her texture's alpha.
  SR1 already makes these solid in the bare path.

So authored-only bare stays refused (correctly), and the BC1 patch (BR1) is the route for the
deleted band. `skin_restore.py`'s description is corrected.

### Defects found and fixed (each with a test in `tests/unit/test_body_completion_join.py`)

Measured on a synthetic fixture (`tests/body_completion_support.py`: the calibration body
subdivided to O's triangle size, a chest band under a VRoid-style top deleted), never on O's
output. `wardrobe/vrm/completion_join.py: measure_join` takes the numbers, and a bare build with
completion now carries them in `bodyCompletion.join`.

| Defect | Before | After |
|---|---|---|
| The patch stopped half a 1 cm row short of her rim (one seal row, vertices at cell centres) | rim to patch 3.14 mm mean, **5.54 mm max** | 1.59 mean, 3.28 max (about `UNDER_SKIN_M` beneath her rim) |
| Smoothing pulled the patch deeper than `UNDER_SKIN_M` under her skin at her sides | 4.1 mm step under her rim | exactly `UNDER_SKIN_M`; 0 vertices in front of her skin, 0 within 0.5 mm of it |
| Skin sampled at 7 points a triangle for the patch's radius grid: cells over her skin read as empty | 1.04 m and 1.17 m rows entirely empty over skin, 6–32 of 72 cells in a dozen more | samples ≤ 3.3 mm apart; none |
| Radial (level) normals | 25.3° from hers at the seam (mean 16.4°) | **6.3°** (mean 1.5°): under her skin it takes her normal, eased into its own over the hole |
| Weights from the nearest *garment* vertex | top rigged like cloth: seam weight difference 1.68 of 2, rim 33.5 mm from the patch arms-down | **0.15**, 7.4 mm (the fixture's own skin tears there by up to 29 mm) |
| Material forced `OPAQUE` where hers is `MASK` | 2 render-state differences | none |
| Patch appended to *her* skin mesh, and her mesh tagged `bodyProxy` | her whole body tagged | the patch is its own mesh and node, on her skeleton, alone tagged |
| `…_Onepiece_00_CLOTH_01/_02` not recognised as clothing (`_CLOTH\b`) | O's black collar and cuff (46 opaque triangles) stayed on a bare build | detected; removed with the dress |

The review packet (`tools/body_surface/review_packet.py --file <built.vrm>`) now opens with
"This file is reconstructed", the regions and the patch mesh, read from the file's own tags; the
import's `checks.body-state` reports `reconstructedRegions` beside `reconstructed`.

Neighbouring patch normals differ by up to 15.3° (her own skin round it: 9.2°). Colour across
the join is 0 on the fixture (one skin tone); on O it is measurable only on a built file.
The authored-accessor fingerprint check is unchanged and still green.

### What is open

- **Design clearance** for `e5c0395b…`: a person's review. The clothed packet is prepared
  outside the tree; its reference pictures are not, because the companion app does not ship
  O, and the turntable that makes them runs in the app.
- **Serving a reconstructed look** is the operator's decision, not made here: (1) review the
  *output* file's SHA-256 in the existing registry and import it through the existing admin
  route, which already reports `reconstructed`; or (2) reconstructed looks stay unservable.
- **Track B** (an artist completes her chest on the source mesh) needs nothing new: the
  delivery requirements are section 6, route 1, of `body-state-specs/vroid-avatar-sample-o.md`.
  The surface to author is the band above: 0.964–1.130 m, all round her at 0.964–1.075 m.
