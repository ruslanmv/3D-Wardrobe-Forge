# develop/cloth_bake — experiment, not part of Forge

Feasibility test for one idea: improve garments **in Forge only** by settling
them offline on the posed avatar with an open-source solver, then turning the
settled shapes into skin weights the viewer's `master` already draws. If it
worked, `tools/audit/prove_three_garments.py` with `--forge-url` pointed at a
proxy that serves re-weighted looks would beat Forge `main`.

Nothing here is imported by Forge, run by CI, collected by pytest or linted
by ruff (there is no Python in this folder). Delete the folder to remove it.

## Result (2026-11-08): not feasible with Rapier as the solver

**Verdict: stop.** On the real A-line dress the Rapier settle is worse than
plain skinning in every pose, so there is nothing better to fit weights to.
The remaining steps (weight fit, proxy, audit run) were not built.

`dress-a-line-v1` on `fem_vroid`, Forge branch build (bodice pinned), 60
frames, softness 120 Hz, her posed body as a triangle-mesh collider. Signed
depth against her skin, sign checked at her pelvis and chest centres
(negative) and half a metre away (positive).

| Pose           | Skinned: max mm / inside / stretch | Rapier settled: max mm / inside / stretch | Solve  |
| -------------- | ---------------------------------- | ----------------------------------------- | ------ |
| standing       | 15.4 / 0.38 % / 1.00               | 15.4 / 2.08 % / 1.99                      | 43 s   |
| sittingDesk    | 32.8 / 7.70 % / 2.74               | 32.8 / 8.27 % / 2.82                      | 56 s   |
| sittingWide    | 25.8 / 8.27 % / 3.00               | 25.8 / 9.15 % / 4.03                      | 60 s   |
| sittingCrossed | 25.0 / 7.20 % / 2.74               | 25.0 / 10.92 % / 2.84                     | 83 s   |

Variants tried on Sitting Wide: `ORIENTED` body collider 25.8 / 5.43 % / 3.87
(60 frames); `ORIENTED` + `MERGE_DUPLICATE_VERTICES` 25.8 / 10.86 % / 3.85
(120 frames, 123 s).

Why:

1. **Cloth that starts inside her is not pushed out.** Seated skinning puts
   ~8 % of the dress inside her thighs before any physics. Contacts against a
   triangle mesh have no notion of which side the cloth should end on, so the
   solver leaves those particles in, or drags neighbours in after them.
2. **Half the penetration is pinned.** Seated, 40–70 pinned bodice vertices
   at the hip crease are up to 33 mm inside her; no solver is allowed to move
   them. That is a Forge pin-region question (PA1 pins the whole bodice),
   not a solver question.
3. **Slow.** 43–123 s per pose for 1536 particles (deformable surface against
   an 11k-triangle mesh). Acceptable offline for one garment, not for a
   catalog.

## What did work

- Posing the avatar outside the browser exactly as the viewer does: three r147
  + three-vrm 2.1.0 (the viewer's pair, installed with `legacy-peer-deps`),
  presets from `poses.json` (copied from the viewer's `VRPoseSystem.js`).
- Reading WCL1 and the garment in file vertex order (1584 render vertices =
  WCL1 binding).
- A trustworthy signed-depth probe (after three bugs, below).
- `py-dem-bones` 0.13.1 (BSD-3-Clause): builds from the sdist in about a
  minute and imports. The weight-fitting step is available if a solver ever
  gives a better target.

## Measurement bugs found on the way (do not repeat)

1. Querying the solver's own world: the projection snapped onto the garment's
   surface collider and a dress nowhere inside her read 32 % inside.
2. Querying a fresh Rapier world before one `step()`: every query returns
   nothing, so everything read 0 mm.
3. Using Rapier's triangle feature ids for the sign: it cleans the mesh, ids
   don't match ours, and points 10 cm outside her read inside.
   The probe now projects with Rapier and takes the sign from the nearest
   posed vertex normal. A sanity check must use absolute truth (inside a bone,
   far outside the body), not "5 mm along the same normals the probe uses".

## Run

```bash
cd develop/cloth_bake
npm install                          # rapier 0.21.0, three 0.147.0, three-vrm 2.1.0 (pinned)
# a look built by this Forge branch, e.g. via the API or tools/gallery scripts
node bake.mjs --vrm out/looks/aline.vrm --template dress-a-line-v1 --frames 60 \
  --out out/aline-bake.json          # prints per-pose metrics, writes *-report.json
TRIMESH_FLAGS=ORIENTED node bake.mjs ...   # collider variants
```

## If someone picks this up

Do not tune Rapier further on this setup. Try, in order, each judged by
`tools/audit/` against Forge `main`:

1. Pin only the waistband and the bodice above the hip crease, so seated
   thighs can push the lower bodice (Forge, PA1 follow-up).
2. A solver that resolves starting penetration: Blender's cloth (Forge already
   has `Dockerfile.blender`; Blender is not installable in this sandbox:
   no binary, and no `bpy` wheel for Python 3.13). Its collision has
   explicit inside/outside handling and thickness.
3. Only with a better settled target: fit weights with `py-dem-bones`, serve
   through a proxy, and run `prove_three_garments.py` against `main`.
