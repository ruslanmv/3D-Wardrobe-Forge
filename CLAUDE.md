# Working in this repository

Standing context for Claude Code sessions. Fix this file in the same change if
something here turns out wrong.

## What this is

3D Wardrobe Forge: a Python service (FastAPI API + worker) that dresses VRM
avatars and serves the looks to the 3D Avatar Chatbot (`ruslanmv/3D-Avatar-Chatbot`,
its `src/wardrobe/`). Python ≥ 3.11, dependencies in `.venv/`.

- Base branch: **`ultimate`**. Work on a `claude/…` branch and open PRs into it.
- The chatbot repository is usually checked out beside this one
  (`/home/user/3D-Avatar-Chatbot`), and its viewer renders Forge's VRMs (see
  _Looking at results_).

## Branches, merges and deploys (the owner's rules, 2026-11-20)

- **Never merge or push to `main`.** `main` is the owner's, after their own audit. Every
  change goes `claude/…` branch → PR into `ultimate` → merge (title and body `Updates`).
  A merge into `main` once deployed un-audited code (PR #80); do not repeat it.
- **The Space deploys from `ultimate`, by hand:** Actions ▸ Deploy to Hugging Face Space ▸
  Run workflow ▸ branch `ultimate` (`deploy-space.yml` checks out the branch picked). A push
  to `main` also deploys — another reason never to touch it.
- **A session cannot start workflows** (GitHub answers 403 to a dispatch from Claude Code):
  ask the owner to run Deploy, or Prebuild wardrobe (`missing_only` yes, `overwrite` no;
  `private_looks` yes for BD21 in a second run with `only` set to `none`; `slugs` limits it to
  named characters). Its inputs are drop-downs, not tick boxes: GitHub's phone site shows no box.
- **A detail review recorded in the Studio lives on the Space's disk**, which is lost at restart
  and which the Prebuild runner never sees. It counts there only once committed
  (`assets/body_surface/adult-detail-reviews.json` and its packet, under the reviewer's name).
  Until then, build that character's detailed looks in the Studio on the Space itself.
- **After any deploy:** `.venv/bin/python tools/qa/space_smoke.py` (routes, gates refuse a
  guest, no Private to a guest, warm timings), `FORGE_GRANT=… .venv/bin/python tools/qa/grant_check.py`
  (what the companion's read grant opens — body catalogue, After Dark, After Dark · Bare — and that
  a guest gets none of it; the grant from the environment only) and `node tools/qa/studio_shot.cjs --out <scratch>`
  (the Collections browser, desktop and phone; `--admin-token-file` for the admin view). Look at
  the frames. The registry's first call after a restart is ~18 s (cold), then ~0.3 s.
- **Populate the dataset from a session** (when the Prebuild workflow cannot be started):
  `tools/dataset_missing.py` (what is missing, read-only), then
  `HF_TOKEN=… tools/populate_dataset.sh [slugs]`: one character per fresh Forge, `--missing-only`,
  publish without `--overwrite` (the dataset's entry wins), local files deleted per character, a
  watchdog stopping under 3 GB disk / 1.5 GB memory. Needs `pip install -e ".[hf]"` and
  `tools/fetch_library.py`. Run it detached (`setsid nohup … &`) and watch the log: a character
  takes hours. The token lives only in the environment — never a file, commit or log.
- Local Forge for the Studio: `WARDROBE_ADMIN_PASSWORD=<random> WARDROBE_STORAGE_ROOT=<scratch>
  .venv/bin/python -m uvicorn apps.api.main:app --port 8091`, then `POST /v1/admin/session`
  for a token kept in an owner-only scratch file, deleted when done.

## The gate (what CI runs, `.github/workflows/ci.yml`)

```bash
.venv/bin/python -m ruff check .                       # must pass
.venv/bin/python -m pytest tests/unit tests/integration -q -n auto
```

- `ruff format` is **not** enforced (most files are not formatted). Format only
  files you create, or leave formatting alone.
- In a cloud container, the whole suite in one process can be killed for memory.
  Run the files you touched instead, e.g.
  `.venv/bin/python -m pytest tests/unit/test_body_detail.py tests/integration/test_bare_body.py -q`.
- Plain `python` lacks the deps (`pydantic_settings`). Always use `.venv/bin/python`.

## Bare bodies and body detail (BD1–BD21): where things are

| What                                       | Where                                                              |
| ------------------------------------------ | ------------------------------------------------------------------ |
| Bare pipeline (gates, strip, restore, tag) | `wardrobe/pipeline/bare_body.py`, `wardrobe/body_surface/eligibility.py` |
| Anatomy painter (vulva, anus, nipples, hair, relief) | `wardrobe/vrm/body_detail.py` (`_pelvis`, `_height`, `_hair`) |
| Effects, marks, tattoos, piercings, semen, oil | `wardrobe/vrm/skin_effects.py` (`under`, `over`, `fluid`, `relief`) |
| Live state switching (skin packs)          | `wardrobe/vrm/skin_pack.py`; the client is the chatbot's `src/wardrobe/SkinStateSwitcher.js` |
| Presets / states / extras (data)           | `assets/body_detail/presets.json`, `states.json`, `extras.json`     |
| Job options (`bareDetail`, `bareState`, `bareExtras`, `bareStates`) | `wardrobe/domain/jobs.py` |
| Erotic outfits, partial undress            | `wardrobe/body_surface/outfit_dictionary.py`, `docs/qa/EROTIC_SETS.md` |
| What a client is told (BD21): each bare look's `body`, the catalogue | `JobOptions.body_summary`, `GET /v1/body-surface/catalog` (admin or grant) |
| Private categories + body thumbnails (WS3) | `classify.PRIVATE_CATEGORIES`, `wardrobe/registry/body_previews.py`, `tools/render_body_previews.py` (`docs/WARDROBE_REGISTRY.md`) |
| After Dark · Bare: 24 named bare looks (AB1) | `assets/body_detail/bare_looks.json`, `wardrobe/registry/bare_looks.py`; collections `ad-bare*`; the Studio's After Dark ▸ 🔞 Bare (`docs/WARDROBE_REGISTRY.md`); all 24 in one sheet: `tools/body_surface/bare_looks_sheet.py --base <ref-atlas.vrm> --out <scratch>/x.png` |
| Make every private look for every character (BD21) | `tools/prebuild_private.py` (packs of ≤10 states covering all, extras sets); in CI: Prebuild wardrobe ▸ `private_looks` |
| Full notes                                 | `docs/qa/BARE_DETAIL.md` (read before changing the painter)         |

Rules that break things when missed:

- **Everything is painted, never meshed.** Colour layers plus a generated normal
  map. A new structure needs both a tint field in `_pelvis`/`skin_effects` and a
  height in `_height`/`relief`, read from the **same helper**
  (`_minora_width`, `_glans_radius`…), or colour and relief drift apart.
- **Adding a state:** keys must be in `STATE_KEYS`, and every state needs a
  `body` line (what her body is doing, second person, for the conversation).
  **Adding an extra:** keys must be in `EXTRA_KEYS` (`FX.MARK_KEYS`). Piercings
  must be in `FX.PIERCINGS` and tattoos in `FX.TATTOOS`; `load_extras` refuses
  anything else.
- **Brightening tints whiten:** on bright skin a flat multiplier > 1 clips red
  first and turns cyan. Lift blue and green more than red (see `_oil`).
- **A new state is made by the generator without edits** (an `other` pack), but give it a
  group in `tools/prebuild_private.py` `GROUPS` so it lands in the pack its scene uses.
  Each detailed bare look is listed separately (`plan: bare-<key>`); never collapse them.
- **Detail needs clearance:** `eligibility.detail_clearance` needs a full review
  (packet + ≥40 chars of evidence) or the synthetic reference. Never loosen it.
  CG10: the Studio's Review page (`/studio/review.html`) shows every character's
  stage (needs review, needs detail review, cleared, blocked) and what is missing,
  makes Forge's packet for the exact file, and records a person's detail review in
  `adult-detail-reviews.json` beside the write-once design finding (both required).
- Previews of explicit detail are private: never commit them, never serve them
  from a public route.

## Wardrobe registry (WS1): categories, collections, private gating

Every garment and ready look, typed into 20 clothing types and collected into public and
admin-only private collections (Adult ones aligned with the chatbot's Private: striptease,
table dance, undress step by step; Private body ones: naked, gaped, finishes, positions).
`GET /v1/registry`; the admin manager under `/v1/admin/registry/*`; in the Studio, the top bar's Collections (`apps/studio/js/collections.js`, WS2). Rules in `wardrobe/registry/classify.py`, decisions in
`state/wardrobe-registry.json`. Read `docs/WARDROBE_REGISTRY.md` before changing it.

- Three tiers: general, **Adult** (what guests already had; shown to everyone) and **Private**
  (admin only: bare bodies, body states, finishes, marks). `/v1/registry` filters Private on the
  server; the existing endpoints (`/v1/outfits`, `/v1/collections`, `/v1/templates`) are not
  re-gated. Never hide Private content only in the page.
- A finished look is reused, not rebuilt: `prebuilt.keys_for` (words key, plan key; RU4 adds
  explicit layers). Body art and bare requests are never answered from the cache.
- An admin's decision always wins over a rule; a garment is never dropped for lack of a
  collection (All Clothes holds every wearable template).
- **Occasions** (the Studio's Design tab) are `wardrobe/pipeline/occasions.py`: styles of outfit
  dictionary ids only (a test refuses anything else). AD1 **After Dark** is the full adult
  wardrobe as an occasion (striptease, what's underneath, table dance, boudoir, dominant &
  fetish, role-play, barely there, out tonight, mature & elegant), `private=True` like Private
  and GC2 `grant=True`: `GET /v1/outfits` lists it only to an admin session or a valid read
  grant (the companion's second gate); Private stays listed to everyone (gate 1 is the app's). Body states are not outfits: they live in the
  registry's Private categories (Collections), never in an occasion.

## Looking at results (saved tools, fastest first)

```bash
B=<scratch>/ref-atlas.vrm      # unique-UV synthetic adult; first build ~5 min
# 1. Seconds, no renderer: colours at her own coordinates (vulva unrolled, nipple, torso)
.venv/bin/python tools/body_surface/detail_flat.py --base $B --out <scratch>/flat \
    --preset natural --states pumped,open --extras tattoo-mons-rose+piercings-intimate --views pelvis,anus,nipple,torso,back
# 2. VRMs to view (first run without --base writes ref-atlas.vrm)
.venv/bin/python tools/body_surface/detail_preview.py --out <chatbot>/audits/poses/runs/detail \
    --base $B --presets natural --states pumped --extras glitter+hearts
# 3. In the chatbot repo: the app's own viewer and poses
node tools/qa/body-detail-render.mjs --vrm audits/poses/runs/detail/ref-natural-pumped.vrm --views chest,torso,back
```

Outfits end to end (a real job each, the look written to a VRM), then the chatbot's viewer head
to heels — a look that builds is not a look that fits:

```bash
.venv/bin/python tools/body_surface/build_outfits.py --body <scratch>/ref-plain.vrm --out <scratch>/looks --prefix show-
node tools/qa/body-detail-render.mjs --vrm <copy under the chatbot>/<id>.vrm --views full,fullback   # chatbot
```

One build killed for memory takes the whole run down silently: build that id alone (`--ids`).

The flat view shows the fixture's sparse texels as stripes and gaps. That is the
fixture, not the paint. The renderer's pelvis close-ups (`seated`, `kneesup`)
often miss the vulva on this fixture, so use the flat view to judge the vulva.

## Conventions

- **Batch prefixes** in comments and docs: `BD` body detail (BD21 latest), `ES`
  erotic sets, `W`/`WF` wardrobe. Comments say why, at length.
- **PRs and commits for this owner:** PR title and body are just `Updates`.
  Commit messages are `Updates of quality`, and merge commits `Updates`. Do not
  describe the work in them.
- The prebuild dataset (`tools/prebuild.py`, HF `ruslanmv/3d-wardrobe-garments`)
  only adds missing entries with `--missing-only`. Never write a token into a
  file, commit or log.
