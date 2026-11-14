# develop/ — plan for future sessions

How the three things worth keeping from the 2026-11-08 cloth work are carried
from `develop/` into Forge `main`, one session at a time, without repeating
`docs/CLOTH_FAILED_ATTEMPTS.md`.

| Track | What                                                 | Today                                   | Lands in `main` as                          |
| ----- | ---------------------------------------------------- | --------------------------------------- | ------------------------------------------- |
| A     | meshoptimizer for simulation LODs                    | Measured in a scratch run, not in Forge | A build step behind a setting               |
| B     | Seam classification (SB1) and bodice pins (PA1)      | On this branch, on top of #27/#28       | The cloth-asset contract, export off by default |
| C     | Pin less, Blender settle, py-dem-bones weights       | Rapier settle failed (F13)              | Baked skin weights for allowlisted templates |

A and B make the data right. Only C can change a picture. Do them in that
order.

## Rules for every session

1. **One goal per session**, from the list below. Start by reading
   `docs/CLOTH_FAILED_ATTEMPTS.md` and this file.
2. **Work under `develop/<topic>/`.** Nothing in `wardrobe/`, `apps/`, CI or
   the Docker images imports or runs it. Code moves out of `develop/` only by
   the graduation step of its track.
3. **The viewer (3D-Avatar-Chatbot) is not modified.** It is served at its
   `master` for the audit (`docs/WARDROBE_AUDIT.md`).
4. **Judge with the audit against Forge `main`:**
   `python tools/audit/prove_three_garments.py --forge-url <candidate> --reference-prefix /tmp/cloth-main`.
   A pose that looks worse than `main` is a regression whatever the numbers say.
5. **Measure with a probe you have checked against absolute truth** (a point
   at her pelvis centre reads negative, a point half a metre away positive).
   Three probe bugs are recorded in `develop/cloth_bake/README.md`.
6. **A failed step is written up**, as an F-entry in the failure history,
   with numbers. Do not tune past a clear failure in the same session.
7. Pin versions exactly. Record licences where the dependency lands.

## Track A — meshoptimizer for simulation LODs

Evidence: on the pleated mini (7495 particles) meshoptimizer 1.3.0 reached the
1200 desktop budget at 4.2 mm max deviation, every open-boundary vertex kept;
`simplify_particles` stopped at 2037 particles and 92 mm
(`docs/audit/ADDON_ADOPTION_MATRIX.md`).

### A1. `develop/sim_lod/` — reproduce in Forge (one session)

- `lod.mjs` (meshoptimizer pinned at 1.3.0): reads particle positions,
  triangles and a lock mask as JSON on stdin, writes the simplified index
  buffer and achieved error on stdout. `simplifyWithAttributes`, attachment as
  the attribute, open-boundary vertices locked.
- `compare.py`: for every cloth template in the catalog on `fem_vroid`,
  `simplify_particles` vs `lod.mjs` at 200 / 500 / 1200. Report particles,
  max and p95 deviation, boundary kept, components, seam and bridge rows
  kept, time. Use Forge's own `compile_cloth_asset` for the input.
- **Decide the budget rule:** pinned particles are skinned, not simulated.
  Count only free particles against the budget (the pleated mini has 1734
  pinned waistband particles; with them counted, 200 and 500 are unreachable
  by any simplifier).
- Done when: a table for the whole catalog, and a written decision.

### A2. Runtime decision (same or next session)

meshoptimizer's JavaScript package needs Node at export time. Forge's main
image has Node only in its build stage. Pick one and record why:

- add Node to the runtime image for this one step, or
- a Python binding (none was found on PyPI on 2026-11-08 under
  `meshoptimizer`; check again, verify licence), or
- run LODs as a separate build step, not per job.

### A3. Graduation into `main`

- Move `lod.mjs` to `wardrobe/cloth/lod/` (or the chosen binding) and call it
  from `wardrobe/cloth/asset.py` `_lods` **behind a setting**
  (`wardrobe_cloth_lod_engine: "native" | "meshoptimizer"`, default `native`).
- Tests in `tests/unit/`: a hem loop, the 1 mm shell bridge and every pinned
  particle survive; the coarse map never renumbers a particle (F3); deviation
  under a stated limit; `missingSeams` does not increase.
- Audit: pictures identical to `main` (LODs are metadata).
- Flip the default only after one release with both engines compared.
- Rollback: set the engine back to `native`.

## Track B — the cloth-asset contract (SB1, PA1)

These are correct and needed by any future runtime, but the viewer's `master`
does not read them, and they make looks larger (A-line +0.25 MB, pencil
+0.3 MB, pleated +1.3 MB of WCL1).

### B1. Graduation into `main` (one session)

- One PR from `main` carrying #27, #28 and this branch's SB1 / PA1 commits,
  rebased and reviewed together (not stacked).
- **Export behind a setting**, `wardrobe_export_cloth_asset: bool = False`.
  With it off, a look is byte-identical to today's (check with
  `tools/gallery/geometry_hashes.py` and the GLB size). The compiler and its
  tests still run.
- Audit with it on: pictures identical to `main`.
- Done when: merged with the setting off; nothing users download changes.

### B2. Open data fixes found on the way

- Weld the pleated mini's front-centre waistband slit (0.13–6.0 mm, 22
  missing seams) in the generator. This **changes geometry**: regenerate the
  gallery hashes in the same PR and prove the pleated mini with the audit.
- Pin regions for dresses: see C1.

## Track C — a settle that is better than skinning

F13: Rapier, settling the A-line on her real body, was worse than skinning in
all four poses. Two causes, one per step below.

### C1. `develop/cloth_bake/` — pin less of the bodice (one session)

- Half the seated penetration is pinned bodice vertices at the hip crease
  (40–70 vertices, up to 33 mm). Try pinning the waistband and the bodice
  only above the hip crease (a height band from the body's measured hip, not
  a percentage of the garment).
- Measure with `bake.mjs` (no settle needed): pinned vertices inside her per
  pose must fall to near zero, standing must stay clean.
- Done when: a pin rule that clears the pinned penetration, as data for C2.

### C2. `develop/blender_bake/` — Blender's cloth solver (one or two sessions)

- Use Forge's `Dockerfile.blender` (Blender is not installable in a plain
  sandbox; no `bpy` wheel for Python 3.13).
- Import the look, pose her with the same presets (`develop/cloth_bake/poses.json`),
  body as a collision object with thickness, garment as cloth with the C1
  pins, settle, export settled vertex positions in file order.
- Measure with the same probe as `bake.mjs`, same table as F13.
- **Gate:** in every pose, less of the dress inside her than skinning, a
  smaller deepest point, and stretch not worse than skinning by more than
  10 %. If not, write F14 and stop.

### C3. `develop/weight_fit/` — py-dem-bones (one session, only after C2 passes)

- `py-dem-bones==0.13.1` (BSD-3-Clause; builds from the sdist in ~1 min).
- Fit weights for the skirt vertices only, the avatar's skeleton fixed, from
  the four settled poses. Keep vertex order, the bodice weights and four
  influences per vertex.
- Check: re-skin with the fitted weights in each pose and run the probe.
  The fitted result must keep most of C2's gain.

### C4. `develop/proxy/` — the end-to-end proof (one session)

- A small proxy in front of the Forge branch: every request passes through,
  except `GET /v1/assets/looks/<id>/look.vrm`, whose allowlisted garment gets
  the fitted weights (Forge serves relative URLs, so the viewer stays on the
  proxy).
- Run `prove_three_garments.py --forge-url <proxy>` against Forge `main`.
- **Gate:** every seated pose looks better than `main`, standing identical.

### C5. Graduation into `main`

- A Forge export step behind a setting and a template allowlist
  (`wardrobe_baked_weights: list[str] = []`), starting with
  `dress-a-line-v1`; then pencil, then pleated, each with its own audit.
- The bake runs in the Blender worker at export time; the native engine
  path is unchanged when the list is empty.
- Rollback: empty the list.

## Session prompts

Copy one into a new session. Each assumes this branch, or `main` once it
carries `tools/audit/`.

```text
Forge only. Read docs/CLOTH_FAILED_ATTEMPTS.md and develop/PLAN.md.
Do Track A, step A1: build develop/sim_lod/ with meshoptimizer 1.3.0 pinned, compare it
with simplify_particles on every cloth template on fem_vroid, decide the budget rule for
pinned particles, and write the table and the decision into develop/sim_lod/README.md.
Do not touch wardrobe/ or CI.
```

```text
Forge only. Read docs/CLOTH_FAILED_ATTEMPTS.md and develop/PLAN.md.
Do Track B, step B1: one PR from main with the cloth-asset contract (#27, #28, SB1, PA1),
export behind wardrobe_export_cloth_asset=False, looks byte-identical with it off, audit
identical to main with it on.
```

```text
Forge only. Read docs/CLOTH_FAILED_ATTEMPTS.md, develop/PLAN.md and develop/cloth_bake/README.md.
Do Track C, step C1: find a pin rule for dresses that clears the pinned bodice penetration
when seated, measured with develop/cloth_bake/bake.mjs; then C2 if time allows. Stop and
write F14 if the Blender settle is not better than skinning in every pose.
```
