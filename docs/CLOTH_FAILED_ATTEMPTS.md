# Cloth physics: what was tried, what failed, and what not to repeat

Written 2026-11-08, at the end of two rounds of work on seated skirts and
dresses. **No attempt produced a garment that looks better than the viewer's
`master`.** The viewer (3D-Avatar-Chatbot) is therefore frozen at `master`, and
garment work continues here, in Forge, proved with `tools/audit/` against Forge
`main` (`docs/WARDROBE_AUDIT.md`).

Read this before starting any cloth work. Every entry below cost real time,
and each one looked promising in its own unit tests and numbers.

## Who did what

- **Round 1 (2026-11-07 to 2026-11-08), the earlier stack.** Viewer PRs #135–#141
  and Forge PRs #26–#28. Commits are authored "Cursor Agent" and from the owner's
  account; the project owner reports the work was driven from a brief written
  for Grok, and that it did not manage to build a working engine. The record
  below is what the code and captures show.
- **Round 2 (2026-11-08), this branch.** Viewer PR #142 (M1, M2), Forge PR #29
  (SB1, PA1), the master comparison, and the audit move into Forge. It fixed
  real data defects but **also did not reach an acceptable garment**.

Both rounds made the same structural mistake: they measured each change
against the change below it, never against `master`.

## The failed attempts

Gate limits throughout: penetration ≤ 1 mm, edge stretch ≤ 6x, span drop ≤ 8 mm.
"Picture" means the four-camera captures of `fem_vroid` in the real viewer.

### F1. Heuristic lifts in the default pose corrector (round 1)

- **What:** seated "span lifts" and a hem "seat" for skirts in
  `PoseClothCorrection.js`: `b345da3` (#136), `07ed700` and `a901d04` "keep a
  seated skirt open over the briefs" (#137), `017aec6` risen-hem walk (#140).
  About +587 lines on the **default page**.
- **Result:** against `master`, the seated A-line and pencil skirt **got worse**.
  The skirt leaves the lap and hangs behind the knees in every seated side
  view (`audit/2026-11-08/master-vs-branch-{aline,pencil}.webp`, middle row).
- **Why it failed:** each lift is a guess about where cloth should be, applied
  after skinning, with no physics behind it. It moves the hem to satisfy a
  number (span drop) and loses the shape.
- **Do not:** add percentage lifts, hem walks or "open the skirt" rules to the
  default path. Never change the default page from an experiment.

### F2. A 24-frame XPBD "settle" beside the corrector (round 1)

- **What:** `623d0b2` (#138), then `487ad55`…`e940b7b` (#140): an opt-in
  (`?cloth=xpbd`) XPBD preroll for three skirts, run once per settled pose.
- **Result:** standing A-line opened at the waist at **9.29x** stretch and
  24 mm penetration.
- **Why it failed:** not the solver. See F3–F7: the data under it was wrong.
- **Do not:** start a solver before the asset, the binding and the pins are
  proved correct on a real garment.

### F3. Simulating a mesh whose vertices had been renumbered (round 1)

- **What:** three-vrm's `removeUnnecessaryVertices` renumbers every indexed
  mesh by first use. The WCL1 binding addressed the file order. GLB prefix
  `0, 1, 34, 0, 34, 33` became `0, 1, 2, 0, 2, 3` in the browser.
- **Result:** particles written onto the wrong vertices. The 9.29x tear in F2.
- **Fixed in round 2 (M1, viewer #142):** cloth meshes skip the compaction
  under the flag. Stretch fell to 1.25–1.32x. **Correct, but not enough.**
- **Do not:** let any loader, optimiser or simplifier (three-vrm,
  meshoptimizer, a GLTF pipeline) renumber a mesh that carries a binding.

### F4. Bind-space rest lengths on a posed garment (round 1)

- **What:** constraints rested at T-pose lengths while particles started in
  the skinned pose. The A-line's 1 mm bodice/skirt bridges were pulled back
  toward the T-pose.
- **Result:** worst constraint 1.00 → 2.17 in 24 frames; a beige gap opened
  at the waist.
- **Fixed in round 2 (M2):** rests from the skinned start pose, authored length
  kept beside it. Correct; did not make the garment acceptable.
- **Do not:** apply a global rest-length multiplier to "fix" this.

### F5. Thigh capsules sized from the bone (round 1)

- **What:** radius `0.29 × upper-leg length` = **102 mm** on `fem_vroid`,
  whose thigh skin sits ~60–84 mm from the bone.
- **Result:** the capsule began outside the skin and shoved the skirt out from
  inside it: ~10^5 collision reports per standing settle.
- **Fixed in round 2 (M2):** radius measured from the posed body (median of
  nearby vertices): 60.4 mm standing, 62–68 mm seated.
- **Still wrong:** two thigh capsules are the **only** body collider. Standing,
  the solver reported strain 1.8 while **11.6 %** of the dress was inside her
  (75 mm worst) at the hips and buttocks.

### F6. Lifting the hem band onto the lap (round 1)

- **What:** `BodyCollision.collideLap` raised every particle of the bottom
  10 cm of the garment to the top of the thigh capsule.
- **Result:** a **floating hoop** at hip height with the briefs in the opening.
  Sitting Wide: 30.9 mm / 2.87x / 87.9 mm. In round 2 the same lift tore the
  skirt ~4 cm off the bodice (solver strain **40.6**).
- **Do not:** move a whole band of particles to a height. A hem rests on a lap
  through contact, not through a lift.

### F7. Pinning a dress by its neckline (round 1)

- **What:** with no waistband section, Forge pinned the top 4 cm by height.
- **Result:** the bodice hung from the shoulders; the hip join was a free edge.
- **Fixed in round 2 (PA1, Forge #29):** a `*-bodice` section is an attachment
  region. The standing bodice closed. **Still a flap at the hip and a hoop when
  seated** (F5, F6).

### F8. Calling every near pair of open edges a missing seam (round 1)

- **What:** Forge #28 counted open edges within 15 mm as missing seams.
- **Result:** the A-line (32 "seams") and pleated mini (1129) refused to
  simulate. The A-line's were one 1.0 mm shell offset; 1107 of the pleated
  mini's were its hem folding back on itself.
- **Fixed in round 2 (SB1, Forge #29):** shell bridges ≤ 1.5 mm between
  loops, folds = same loop and a short walk. 22 real gaps remain on the
  pleated mini: an unwelded front-centre waistband slit 0.13–6.0 mm wide.
- **Do not:** sew anything from proximity alone.

### F9. A custom decimator for simulation LODs (round 1)

- **What:** `simplify_particles`, shortest edge first, no error metric.
- **Result:** on the pleated mini it never reached the 1200 budget (stopped at
  2037 particles) and moved the surface by up to **92 mm**.
- **Do not:** keep it. See meshoptimizer below.

### F10. Judging by the gate instead of the picture (both rounds)

- The standing A-line on round 2's best build read **1.28x stretch** with a
  flap sticking out of her hip.
- The first three-garment summary on the frozen viewer printed **"pass" for
  twelve poses nobody had measured** (the viewer reports no metrics; the
  capture tool writes `gate.ok = true` when it found nothing). Fixed: those
  poses now read "not measured".
- **Do not:** treat a passing number as a passing garment.

### F11. Stacking unverified PRs (both rounds)

- #135 → #136 → … → #142, each reviewed against the branch below it. Nobody
  photographed `master` until the end, so the default-page regression in F1
  rode along from #136 to #142 unnoticed.
- **Do not:** open a cloth PR without the master-versus-candidate sheet from
  `tools/audit/prove_three_garments.py`.

### F12. Capturing while the code changed (round 2)

- One pencil-skirt run was captured while the viewer's files were being
  edited (the viewer serves source live), so it mixed two builds. It was
  discarded and re-run.
- **Do not:** edit the served tree during a capture. Use a separate checkout.

### F13. Rapier as an offline bake solver (round 3, `develop/cloth_bake/`)

- **What:** pose `fem_vroid` outside the browser exactly as the viewer does,
  settle the A-line with Rapier 0.21 against her posed body as a triangle-mesh
  collider, then fit skin weights (py-dem-bones) and serve re-weighted looks.
- **Result:** the settle is **worse than plain skinning in every pose**
  (Sitting Wide: inside 8.3 % → 9.2 %, stretch 3.0 → 4.0x; the deepest point
  never improves), 43–123 s per pose. The weight fit, proxy and audit run were
  not built: there was no better target to fit.
- **Why:** cloth that starts inside her is not pushed out by contacts against
  an open triangle mesh, and half the seated penetration is in pinned bodice
  vertices no solver may move.
- **Do not:** keep tuning Rapier on this setup. Details and the next two
  things to try: `develop/cloth_bake/README.md`.

## Rules that come out of this

1. Compare with the reference first: viewer `master` + Forge `main`.
2. Fix the data before the solver: vertex identity, seams, pins, rests.
3. A garment is acceptable only when every pose of the three pilots looks at
   least as good as the reference, and then the numbers are checked.
4. Opt-in flags for experiments; the default page changes last, if ever.
5. No heuristic lifts, no global multipliers, no proximity sewing.

## The open-source projects we tested

All were checked by installing the exact version into a scratch directory and
running it, not from documentation. Full data: `audit/ADDON_ADOPTION_MATRIX.md`.

| Project | Version | Licence | What we measured | Recommendation |
| --- | --- | --- | --- | --- |
| **meshoptimizer** | 1.3.0 | MIT | Pleated mini, 7495 particles: 1200 at **4.2 mm** max deviation (p95 2.0 mm), every open-boundary vertex kept, 59 ms. Floors at 749 (57 mm, a damaged skirt). | **Adopt in Forge**, build time only, to replace `simplify_particles` (F9). Its index buffer keeps the original vertex array, so particle identity is never renumbered (F3). 200 and 500 budgets are not reachable while all 1734 waistband pins are locked; stop counting pinned particles against the budget. |
| **Rapier** (`@dimforge/rapier3d-compat`) | 0.21.0 | Apache-2.0 | The soft-body API is real: built our A-line from raw positions + WCL1 edges (1536 particles, 8864 edges); `setParticleKinematicTarget` pins followed exactly; `init()` 83 ms, step 3.6–6.6 ms, first step 70–91 ms. Default material: **34x** strain; 120 Hz softness 2.7x, stiffer 7–8x. | **Prototype only after** the data and a full-body collider exist. Tried offline as a bake solver with her real body as collider (F13): worse than plain skinning in all four poses. It does not fix F3–F8, and its colliders still have to come from the avatar's real body. 1.66 MB gzip; never on the default page. |
| **three-mesh-bvh** | 0.9.18 latest; **0.5.23 usable** | MIT | 0.9.x needs three ≥ 0.159; the viewer runs r147. 0.5.23 accepts r147 but has no `SkinnedMeshBVH`. Not run on a garment. | **Diagnostics first**: build it over the posed body positions the corrector already computes, to show where F5's 75 mm points are. Not a cloth model. |
| **JoltPhysics.js** | 1.1.1 | MIT (npm field) | Not run. 12.7 MB package; every object needs manual `destroy`. | **Reference only** until Rapier fails a criterion it was meant to win. |
| **PositionBasedDynamics** | — | MIT | Not installed; C++ reference. | **Reference only** for XPBD constraint formulas. |
| **three-vrm spring bones** | 2.1.0 (in the viewer) | MIT | Not a surface model. Its `removeUnnecessaryVertices` caused F3. | Hair, ribbons, loose accessories only. **Never** a skirt. |
| **Ammo.js** | 0.0.10 (2022) | none on npm | Not run. Unmaintained. | **Reject.** |

What none of them can do: fix a wrong binding, a wrong seam, a wrong pin, or
a collider that is not the body. Those caused most of F2–F8.

## Suggested direction (untested; prove each step with `tools/audit/`)

With the viewer frozen at `master`, only changes to what Forge exports can
show up in a picture: geometry, fit, skin weights, materials. Cloth metadata
(`wardrobe.cloth/1`) is invisible to `master`.

1. **Weld the pleated mini's waistband slit** in the generator. Small, visible,
   and SB1 then lets the asset simulate in any future runtime.
2. **Adopt meshoptimizer** for the simulation LODs (above). No picture change;
   removes F9.
3. **Bake, don't simulate, for seated poses.** Forge already has a Blender
   worker (`worker/blender/`). Blender's own cloth solver (mature, open source)
   could settle each pilot garment once per seated pose on the real body at
   export time, and Forge could ship the result as data the viewer already
   draws (for example better skin weights for the skirt's front panel, or
   pose-corrective shapes once a viewer reads them). Nothing runs on the
   phone. This has **not** been tried; it is the path that avoids building a
   real-time engine, which both rounds failed to do.
4. Only after that: a runtime solver (repaired XPBD or Rapier) behind a flag,
   with a whole-body collider, judged by the master sheet.
