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
