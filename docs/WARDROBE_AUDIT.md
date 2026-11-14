# Wardrobe visual audit

Read `docs/CLOTH_FAILED_ATTEMPTS.md` first: what was tried, why it failed, and
the open-source physics projects we tested.

How a Forge change is proved before it ships: the garments it produces are
photographed in the real viewer, beside the same garments from Forge `main`,
and a pose that looks worse than `main` is a regression whatever any number
says.

The tools are in `tools/audit/` (moved here from 3D-Avatar-Chatbot's
`audits/wardrobe_sitting_desk/` on 2026-11-08; `tools/audit/README.md` is the
original manual, paths updated). The viewer repository is **not modified**: it
is checked out at its `master` and only served.

## The three pieces

| Piece     | What                                        | Where                                                   |
| --------- | ------------------------------------------- | ------------------------------------------------------- |
| Viewer    | 3D-Avatar-Chatbot `master`, unchanged       | `http://127.0.0.1:8080/`                                |
| Reference | Forge `main`                                | `http://127.0.0.1:8091`                                 |
| Candidate | Forge, your branch                          | `http://127.0.0.1:8090`                                 |

Both runs use the same viewer, so any difference in the pictures comes from
Forge.

## Setup, once

```bash
pip install -r tools/audit/requirements.txt     # playwright, pillow
```

```bash
# The viewer: master, outside this repository, never edited.
git clone https://github.com/ruslanmv/3D-Avatar-Chatbot /tmp/viewer
cd /tmp/viewer && npm ci && PORT=8080 npm start
```

```bash
# Forge main as the reference (a worktree, so the installed package is not used)
git worktree add /tmp/forge-main origin/main
cp assets/library/fem_vroid.vrm /tmp/forge-main/assets/library/
cd /tmp/forge-main && python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8091
```

```bash
# Your branch as the candidate, from this checkout
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8090
```

`fem_vroid.vrm` is not committed (`assets/library/*.vrm` is ignored). Fetch it
with `tools/fetch_library.py`, or copy it from the viewer's
`vendor/avatars/fem_vroid.vrm`; the SHA-256 must match `assets/library/models.json`.
If a capture tool needs Chromium from a non-default place, set
`PLAYWRIGHT_CHROMIUM` to its binary.

## Prove three garments before the full catalog

| Key       | `--only`       | Template                |
| --------- | -------------- | ----------------------- |
| `aline`   | `A-line dress` | `dress-a-line-v1`       |
| `pencil`  | `Pencil skirt` | `skirt-pencil-v1`       |
| `pleated` | `Pleated mini` | `skirt-pleated-mini-v1` |

```bash
# reference: viewer + Forge main
python tools/audit/prove_three_garments.py \
  --url "http://127.0.0.1:8080/?cloth=xpbd" --forge-url http://127.0.0.1:8091 \
  --out-prefix /tmp/cloth-main
```

```bash
# candidate: viewer + your Forge branch, with the sheets against main
python tools/audit/prove_three_garments.py \
  --url "http://127.0.0.1:8080/?cloth=xpbd" --forge-url http://127.0.0.1:8090 \
  --out-prefix /tmp/cloth-contract --reference-prefix /tmp/cloth-main
```

Each run is `capture.py` with the agreed shape: `--source catalog`, avatar
`fem_vroid.vrm`, poses `standing,sittingDesk,sittingWide,sittingCrossed`,
cameras `front,right,back,left`. The script checks that each catalog name
still resolves to its template, writes `<prefix>-summary.json` and `.md`, and
with `--reference-prefix` writes `<prefix>-<key>-vs-master.png` (top row the
reference, bottom row the candidate). It exits 1 if a garment failed to
capture or resolved to another template. `--only aline` runs one garment;
`--no-capture` rebuilds the summary from captures already on disk.

`?cloth=xpbd` is a no-op on the viewer's `master` (there is no solver there).
It is kept so the command is the same one a future viewer solver will be
judged with.

**Gate column.** The viewer's `master` reports no cloth metrics, so every pose
reads "not measured". The summary never calls that a pass: `capture.py` writes
`gate.ok = true` when the page reported nothing, and an earlier version of the
summary printed twelve passes nobody had measured.

**What decides.** The sheets. A pose where the candidate looks worse than the
reference blocks the change. Numbers are necessary when they exist, never
sufficient: a dress at 1.28x stretch had a flap sticking out of her hip.

## The rest of the audit

`tools/audit/README.md` has the full manual: whole-catalog runs
(`capture.py --source catalog`), the picture review (`review_pictures.py`), the
matrix printer (`print_matrix.py`) and the recorded reports under
`tools/audit/reports/` (the 2026-11-07 catalog matrix and live catalog, the
pencil captures, solver evidence). Those reports are evidence and stay byte for
byte; do not regenerate them in place.

The audit's unit tests run with Forge's own suite
(`tests/unit/test_wardrobe_audit_tools.py`).

## Evidence from 2026-11-08

- `audit/2026-11-08/master-vs-branch-{aline,pencil,pleated}.webp`: rows are
  the viewer's master, the viewer's cloth stack (#135–#142) on its default
  page, and the same stack with `?cloth=xpbd`. The stack was worse than master
  on the seated A-line and pencil, which is why the viewer is frozen at master.
- `audit/2026-11-08/baseline-{aline,pencil,pleated}.webp`: master viewer with
  this branch's Forge, against master viewer with Forge `main`. Every pose
  matches. This branch's cloth changes (SB1 shell bridges, PA1 bodice pins) are
  WCL1 metadata the viewer's master does not read, so they cannot change a
  picture yet.
- `audit/ADDON_ADOPTION_MATRIX.md`: meshoptimizer, Rapier, three-mesh-bvh, Jolt
  and Ammo, measured on installed packages and on this repository's real
  garment assets.

## What a Forge change can and cannot show here

With the viewer frozen at `master`, a Forge change shows up in the audit only
if it changes what the viewer draws: garment geometry, fit, materials,
foundation, templates. Cloth-asset metadata (`wardrobe.cloth/1`) is invisible
until a viewer reads it. Start Forge work that is meant to be seen with a
geometry or fit change, for example welding the pleated mini's front-centre
waistband slit (0.13–6.0 mm, found by SB1).
