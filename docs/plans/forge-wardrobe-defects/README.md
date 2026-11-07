# Forge wardrobe defects — start here

This folder is the work order for the three missing leggings previews and the seated-jeans opening that belongs in this repository. The chatbot audit recorded the same ids. The fixes happen here.

The next coder starts on this branch and does not open a second plan.

## What is already known

On 2026-11-07 the public catalog at `https://ruslanmv-3d-wardrobe-forge.hf.space/v1/catalog/garments` listed 62 garments. Three of them had `previewStatus: pending` and `previewUrl: null`:

| Id | Template | Mesh |
| --- | --- | --- |
| WARDROBE-UI-F181 | `trousers-leggings-v1` | `procedural:leggings` |
| WARDROBE-UI-0523 | `trousers-leggings-highwaist-v1` | `procedural:leggings` |
| WARDROBE-UI-CC4A | `trousers-leggings-seamless-v1` | `procedural:seamless-leggings` |

The catalog path (reference base, then the template) refused all three because the front groin sat inside the radial hull that bridges the thighs. Those rows are marked and left out of that check. This checkout now has a generated 480×640 WebP for each, with `fitPassed: true` in `assets/catalog/build-report.json`. The live Space does not update until that build is deployed. `avatar-sample-a.vrm` stays out of git; fetch it with `make library` or `python tools/catalog/fetch_reference_avatar.py --avatar avatar-sample-a`.

`WARDROBE-DEFORM-002` is the seated straight jeans. HomePilot showed the hips open after penetration had already gone to 0 mm. Forge has not yet measured that pose. The issue stays open until `pose_contact` says whether the opening is in this repository.

`WARDROBE-CLIP-001` (the seated pencil skirt) is listed under `outOfScope`. It is owned by `3D-Avatar-Chatbot`.

## Commands

From the repository root:

```bash
python tools/catalog/check_forge_defects.py
```

Exit 1 means at least one issue is still open. Exit 0 means every issue in `issues.json` satisfies its `verify` block. A jeans pass also needs the pose file:

```bash
python tools/catalog/check_forge_defects.py --pose-report /tmp/forge-qa/jeans-verdict.json
```

The shape of that file is in [PLAN.md](PLAN.md).

## Order

[PLAN.md](PLAN.md) is the sequence. [issues.json](issues.json) is the record the checker reads. Update an issue's `status` only after its verify block passes. `fixed` and `not-forge` are the two statuses that can pass. `not-forge` is allowed only for `WARDROBE-DEFORM-002`, and only with a pose report whose `visual` is `closed-in-forge`.

## What a finished branch contains

- Fit reports that name the failing check for each leggings template.
- A passing fit and a real `assets/catalog/previews/<id>.webp` for each of the three ids, produced by `tools/catalog/render_templates.py`.
- A pose-contact verdict for `jeans-straight-v1` in Sitting (Desk), and either a mesh fix or a `not-forge` status.
- `python tools/catalog/check_forge_defects.py` exiting 0.
- No invented preview URL and no copied WebP.

Publishing the images to the Hugging Face Space is a separate release. This repository's GitHub push does not update the Space. `docs/GARMENT_CATALOG_API.md` says how that deploy works.
