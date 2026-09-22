# Implementation plan

The plan this upgrade was built to, and the state of each milestone.

## Design decisions taken

Four choices shaped everything else.

**1. A pure-Python VRM layer (`wardrobe/vrm`).**
A VRM is a GLB. Validation, humanoid analysis, body measurement, skinned-mesh
assembly and re-import verification therefore need no 3D application. This is
what lets the full acceptance matrix run in CI on every commit.

**2. The garment shell is *built*, not deformed.**
Deforming a donor mesh onto an unknown body is where shrinkwrap artefacts and
broken weights come from, and it fails differently on every avatar. Templates
declare parameters instead, and the shell is generated at the avatar's own
measurements. This is why M2 passes deterministically.

**3. Two engines behind one interface, sharing one shell.**
`native` runs anywhere; `blender` adds surface accuracy, weight transfer from
the body, body masking and generated-mesh cleanup. Both start from the same
shell, so shape is identical and only quality differs.

**4. Fixtures are generated, not shipped.**
`wardrobe/vrm/build.py` produces humanoid VRMs with four distinct body shapes in
both specs. No third-party binaries, no licence exceptions, and the "different
body proportions" requirement is satisfied by construction.

## Milestones

| Phase | Goal | State |
| --- | --- | --- |
| **M0** Foundation | API, queue, storage, VRM import/export | **done** |
| **M1** First outfit | one VRM + one template → a valid new VRM | **done** |
| **M2** Automatic fitting | the same garment across several different VRMs | **done** |
| **M3** Wardrobe library | tops, dresses, jackets, trousers, skirts, shoes | **done** (17 templates) |
| **M4** AI styling | prompt → template + shape + material | **done** (rule-based; LLM hook present) |
| **M5** AI mesh generation | Meshy/Tripo meshes through cleanup and fitting | **adapters + Blender cleanup written; unverified against the live APIs** |
| **M6** Chatbot integration | `WardrobeClient` + `WardrobeController` + Try-On Haul | **done** |
| **M7** On-demand wardrobe | generate, cache and keep looks per character | **done** |

### M2 is the one that could not be skipped

> If one dress cannot fit avatars A, B, C and D automatically and reliably,
> more AI generation does not solve the real engineering problem.

`tests/e2e/test_acceptance.py` runs **7 garments × 4 body types × 2 VRM specs =
56 combinations**, and for each one re-imports the result and asserts the full
criteria list. All 56 pass.

The four calibration bodies are meaningfully different — 1.48 m to 1.83 m tall,
hip widths varying by more than 1.5× — and a test enforces that they stay that
way, so the matrix cannot quietly become four copies of the same avatar.

### M5 is honestly marked

The Meshy and Tripo adapters are written, their response-shape parsing is
tested, and `worker/blender/fit_generated_mesh.py` implements the cleanup a
generated mesh needs. What has **not** happened is a run against the live APIs:
that needs keys, and it is what `nightly-provider-smoke.yml` exists to do.

Until then the native engine refuses generated meshes with a clear message
rather than pretending it can fit them.

## What got built

```
wardrobe/
  vrm/        glb · document · inspect · measure · skinning · merge · export · build
  geometry/   mesh · procedural · raster
  engines/    base · native · blender · shell · geometry_checks
  pipeline/   context · orchestrator · 8 stages
  providers/  base · templates · mock · remote · meshy · tripo
  policy/     licensing · file_safety
  storage/    object_store · database
  queue/      jobs
apps/         api (5 route modules) · cli
worker/       runner · blender (15 modules)
assets/       17 garment templates · calibration · fixtures
clients/      WardrobeClient.js · WardrobeController.js
tests/        unit · integration · e2e · blender
docs/         11 documents
```

## Bugs the acceptance matrix caught

Worth recording, because each was a real defect that a green unit-test suite
would have missed:

1. **Cross-midline skin binding.** Inverse-distance weighting bound left-shoe
   vertices to the right shin. The pair tore in half on a walk cycle. Fixed by
   restricting a *connected component* that sits on one side of the body to
   that side's bones — while leaving a skirt, which is one shell spanning both
   legs, free to blend, because that is how fabric behaves.

2. **Pose tests ignored the bone hierarchy.** Rotating a shin did not carry the
   foot, so correctly-bound boots read as torn. The test was wrong, not the
   garment.

3. **Floor-length hems anchored to the shins.** A column gown bound to
   `lowerLegs` stretched 4.5× on a walk. Real long skirts hang from the pelvis;
   the fix was to use the schema's existing `coverage` vs `anchors` split. A
   test now enforces it for every long template.

4. **Colour resolution was order-dependent.** "navy blue" resolved to whichever
   of the two equal-length names came first in the dictionary. Now the earliest
   mention wins, longest name breaking ties.

5. **A latent circular import** between `wardrobe.pipeline` and
   `wardrobe.engines` that only surfaced depending on which module was imported
   first.

6. **The chest was being flared out to the fingertips.** Caught by *looking at
   the rendered preview*, not by a test. The radial clearance index records the
   furthest body point per height band and sector, and in a T-pose the arms
   dominate every band at shoulder height — so a sleeveless bodice was pushed
   out to meet them, producing a horizontal red flange across the arms. Fixed by
   classifying body points by nearest bone and measuring a garment only against
   the region it sits on.

7. **A body-axis index says nothing about limb-worn pieces.** Following on from
   (6): the same cylindrical index puts its axis *between* the two feet, so a
   trouser leg's inner surface read as buried inside the body and was pushed
   outward. Resolved with the same connected-component signal used for
   binding — a garment component centred off the midline is worn on a limb and
   is left as built, because it was already lofted around that limb's own bone
   with the clearance applied.

The last two are worth dwelling on: both produced *passing* fit reports while
the geometry was visibly wrong. Clearance measured against the wrong reference
happily reports "passed". Rendering a preview and looking at it is part of the
verification, not decoration.

## Next steps

Roughly in order of value:

1. **Verify M5 against the live provider APIs.** Add keys, let the nightly smoke
   test run, fix whatever the real payloads disagree about.
2. **Spring bones for generated garments.** A long skirt currently deforms
   correctly but has no secondary motion.
3. **Pattern textures.** Material parameters are planned from the prompt;
   generated texture maps are not.
4. **More templates.** The cheapest quality win — new JSON, no new code.
5. **PostgreSQL repositories.** The interfaces are in place; the JSON-on-disk
   implementation is the current durable option.
6. **Authentication.** The service has none by design; it needs a gateway in
   front before public exposure.
