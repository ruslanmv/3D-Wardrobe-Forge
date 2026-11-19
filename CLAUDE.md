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

## Bare bodies and body detail (BD1–BD20): where things are

| What                                       | Where                                                              |
| ------------------------------------------ | ------------------------------------------------------------------ |
| Bare pipeline (gates, strip, restore, tag) | `wardrobe/pipeline/bare_body.py`, `wardrobe/body_surface/eligibility.py` |
| Anatomy painter (vulva, anus, nipples, hair, relief) | `wardrobe/vrm/body_detail.py` (`_pelvis`, `_height`, `_hair`) |
| Effects, marks, tattoos, piercings, semen, oil | `wardrobe/vrm/skin_effects.py` (`under`, `over`, `fluid`, `relief`) |
| Live state switching (skin packs)          | `wardrobe/vrm/skin_pack.py`; the client is the chatbot's `src/wardrobe/SkinStateSwitcher.js` |
| Presets / states / extras (data)           | `assets/body_detail/presets.json`, `states.json`, `extras.json`     |
| Job options (`bareDetail`, `bareState`, `bareExtras`, `bareStates`) | `wardrobe/domain/jobs.py` |
| Erotic outfits, partial undress            | `wardrobe/body_surface/outfit_dictionary.py`, `docs/qa/EROTIC_SETS.md` |
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
- **Detail needs clearance:** `eligibility.detail_clearance` needs a full review
  (packet + ≥40 chars of evidence) or the synthetic reference. Never loosen it.
- Previews of explicit detail are private: never commit them, never serve them
  from a public route.

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

The flat view shows the fixture's sparse texels as stripes and gaps. That is the
fixture, not the paint. The renderer's pelvis close-ups (`seated`, `kneesup`)
often miss the vulva on this fixture, so use the flat view to judge the vulva.

## Conventions

- **Batch prefixes** in comments and docs: `BD` body detail (BD20 latest), `ES`
  erotic sets, `W`/`WF` wardrobe. Comments say why, at length.
- **PRs and commits for this owner:** PR title and body are just `Updates`.
  Commit messages are `Updates of quality`, and merge commits `Updates`. Do not
  describe the work in them.
- The prebuild dataset (`tools/prebuild.py`, HF `ruslanmv/3d-wardrobe-garments`)
  only adds missing entries with `--missing-only`. Never write a token into a
  file, commit or log.
