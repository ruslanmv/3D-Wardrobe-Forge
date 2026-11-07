# Execution plan

Do the steps in order. After each step, run:

```bash
python tools/catalog/check_forge_defects.py
```

The checker stays at exit 1 until the last step. That is the expected baseline on this branch.

## 0. Environment

Python 3.11, from the repository root:

```bash
python -m pip install -e '.[dev,preview]'
python tools/catalog/fetch_reference_avatar.py --avatar avatar-sample-a
python tools/catalog/fetch_reference_avatar.py --avatar fem-vroid
```

Catalog previews use `avatar-sample-a` because `tools/catalog/render_templates.py` and `assets/catalog/build-report.json` do. The jeans pose uses `fem-vroid` because that is the avatar in the HomePilot capture. Both files are checksum-pinned in `assets/library/models.json`. `fem-vroid` is declared adult in `assets/library/policy.json`. The three leggings templates are not adult-gated.

Preview rendering also needs Node, Playwright and Chromium, as `docs/GARMENT_CATALOG_API.md` describes. The fit commands in steps 1 and 5 do not need a browser.

`avatar-sample-a` paints a dark waist band and brown tights on her body. Those pixels show under short garments in every catalog preview. They are not a leggings defect. The build report already records that limitation.

## 1. FORGE-REPORT-001 — name the failing check

`FitReport.passed` in `wardrobe/domain/looks.py` is false when any of these is true:

- `vrmValid`, `humanoidValid`, `weightsValid`, `skeletonPreserved` or `sourceRecoverable` is false
- `clippingCheck` is not `passed`, `clearance-only` or `warnings`
- `errors` is non-empty
- `unplanned` is non-empty

`tools/catalog/render_templates.py` stores `result.reason or result.error or "fit not verified"`. A completed job has neither reason nor error, so the three leggings records all say the same thing.

Edit the failed-record branch so a present fit report contributes:

```python
"clippingCheck": str(result.fit_report.clipping_check),
"checks": result.fit_report.checks,
"errors": list(result.fit_report.errors),
"unplanned": list(result.fit_report.unplanned or []),
```

Print the same four fields from `tools/inspect/fit_look.py`. Extract the dict builder if that is what keeps the unit test off the renderer. Add `tests/unit/test_catalog_failure_report.py`. It must not download an avatar and must not call `render_templates.py`.

The checker looks for the source text `fit_report.checks` and for `clippingCheck` in `fit_look.py`. It also requires `diagnosis` on this issue to be filled for all three template ids, each object having `clippingCheck`, `checks` and `errors`. Copy those from the fit output. Do not invent them.

## 2. Reproduce the three fits

Write outside the repo:

```bash
mkdir -p /tmp/forge-qa
python tools/inspect/fit_look.py --avatar avatar-sample-a \
  --prompt "black Leggings" --template trousers-leggings-v1 \
  --base-body replace-outer --out /tmp/forge-qa/leggings.vrm
python tools/inspect/fit_look.py --avatar avatar-sample-a \
  --prompt "black High-Waist Leggings" --template trousers-leggings-highwaist-v1 \
  --base-body replace-outer --out /tmp/forge-qa/leggings-highwaist.vrm
python tools/inspect/fit_look.py --avatar avatar-sample-a \
  --prompt "black Seamless Scrunch Leggings" --template trousers-leggings-seamless-v1 \
  --base-body replace-outer --out /tmp/forge-qa/leggings-seamless.vrm
```

Paste each printed `clippingCheck`, `checks` and `errors` into `issues.json` under `FORGE-REPORT-001.diagnosis`.

Confirm the high-waist plan actually has rise `high`. `wardrobe/pipeline/plan_outfit.py` maps the phrase `high-waist` to that rise, and the render prompt is the colour plus the template name. If the planned rise is empty, the preview would be the plain pair under another name, and that is a planner bug to fix before rendering.

Where to edit, once the check is known:

| Template | Builder |
| --- | --- |
| `trousers-leggings-v1` | `build_garment("leggings")` in `wardrobe/geometry/procedural.py`, which calls `build_leggings_panel(..., plain=True)` when the body has been measured |
| `trousers-leggings-highwaist-v1` | the same panel with rise `high` (`lower_panels.py` lifts the top by `TOP_ABOVE_WAIST_M`) |
| `trousers-leggings-seamless-v1` | `build_leggings_panel` without `plain`, else `build_seamless_leggings` |

`docs/FIT_QUALITY.md` records earlier leggings failures: a hip ledge where the torso band continued below the crotch, and calves cut because the shin bone sits on the front of the leg. Read that page before adding a new clearance rule. Re-use the existing measurement if the failing check is one of those.

## 3. Make the fit pass, then render

Fix `WARDROBE-UI-F181` first. Re-run its `fit_look.py` command until `fitPassed` is true. Then:

```bash
python tools/catalog/render_templates.py --avatar avatar-sample-a --ids trousers-leggings-v1
python tools/catalog/validate_catalog.py \
  --root assets/catalog/previews \
  --report assets/catalog/build-report.json
```

Repeat for `WARDROBE-UI-0523` and `WARDROBE-UI-CC4A`, one id per render. `--ids` merges into the existing build report. A full catalog render is not required and must not be used to hunt for a green exit.

The published record status is `generated` on a fresh render and `cached` on a later identical run. Both are accepted. `fitPassed` must be true. The canvas is 480×640, from `tools/catalog/preview-style.json`.

The high-waist WebP and the seamless WebP must not be byte-identical to the plain leggings WebP. The checker compares hashes.

Set each issue's `status` to `fixed` only after that issue's preview check passes. Leave the others `open`.

## 4. WARDROBE-DEFORM-002 — measure before editing

```bash
python tools/inspect/fit_look.py --avatar fem-vroid \
  --prompt "blue straight jeans" --template jeans-straight-v1 \
  --base-body replace-outer --out /tmp/forge-qa/jeans.vrm
python tools/inspect/pose_contact.py /tmp/forge-qa/jeans.vrm \
  --poses tests/fixtures/homepilot-poses.json \
  --json /tmp/forge-qa/jeans.contact.json
```

`docs/POSE_CONTACT_QA.md` describes the tool. The output directory has to be outside the repository.

Look at the jeans garment in the `sittingDesk` pose: penetration, the share of vertices inside, and the worst edge. Then render or screenshot a front view of that posed file. The HomePilot frame is not a substitute. HomePilot had already run `PoseClothCorrection`, which drives penetration to 0 mm and still leaves the crotch open.

Write `/tmp/forge-qa/jeans-verdict.json`:

```json
{
  "templateId": "jeans-straight-v1",
  "pose": "sittingDesk",
  "avatar": "fem-vroid",
  "maxPenetrationMm": 0.0,
  "visual": "closed",
  "frame": "/tmp/forge-qa/jeans-sittingDesk-front.png",
  "contact": "/tmp/forge-qa/jeans.contact.json"
}
```

`visual` is `closed` only after you have looked at `frame` and the hips and crotch are covered. `closed-in-forge` means the Forge pose is closed and the HomePilot opening is the chatbot push: set the issue `status` to `not-forge` and use that visual value. Any other opening stays `status: open` until the mesh or the weights change and a new verdict says `closed`.

```bash
python tools/catalog/check_forge_defects.py --pose-report /tmp/forge-qa/jeans-verdict.json
```

Do not add a sheet of geometry over the gap. `tests/unit/test_look_presets.py` already requires a standing gusset. A standing test can stay green while Sitting (Desk) opens. Add a pose-contact assertion only if it can run without the library avatar in CI. Otherwise keep the check in this folder's verifier.

## 5. Done

All five issues have `status` `fixed` or, for the jeans only, `not-forge`. The checker exits 0. `python tools/catalog/validate_catalog.py` accepts the preview directory.

Say in the pull request that the Hugging Face Space still serves the old catalog until its own release. Do not claim the live `previewStatus` changed until a GET after that release shows `ready`.

## Tests to run before the pull request

```bash
python -m pytest tests/unit/test_check_forge_defects.py tests/unit/test_catalog_failure_report.py -q
python -m pytest tests/unit/test_look_presets.py tests/integration/test_catalog_api.py -q
python tools/catalog/check_forge_defects.py --pose-report /tmp/forge-qa/jeans-verdict.json
```

`test_catalog_failure_report.py` does not exist yet. Step 1 adds it. The other three exist. The catalog API test proves a missing file stays `pending`; do not weaken it.
