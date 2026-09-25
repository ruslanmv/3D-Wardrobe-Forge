# Lingerie quality upgrade plan

> Status: in progress. **L2 done**: flat ribbon straps between anchors
> (`wardrobe/lingerie/straps.py`, `contract.py`, `specs.py`; the ribbon moved to
> `wardrobe/geometry/ribbon.py`). **L1 done**: the fashion-fit forms
> (`wardrobe/vrm/fashion_body.py`, declared adult in
> `assets/calibration/policy.json`) and the landmarks
> (`wardrobe/lingerie/landmarks.py`), tested in `tests/unit/test_fashion_form.py`.
> It answers the visual
> review of looks #2–#11 (clearance passed, but the garments were not built the
> way lingerie is built) and follows the owner's priority order. Every file and
> function it names was read in this repository.

The code review behind the lingerie analysis holds. Reading further turned up six facts that shape the plan:

- **The mannequin can't go into `CALIBRATION_BODIES`.** `wardrobe/vrm/build.py CALIBRATION_BODIES` is parametrized over by `tests/unit/test_measure.py`, `test_skirt_fit.py`, `test_haul_library.py` and `test_geometry.py`. The gallery body is `tools/gallery/looks.py BODY = calibration-c-tall`. Adding to the tuple would change tests and hashes, so the new mannequin needs its own tuple.
- **The body has no feet and no crotch.** `build_body_mesh` sweeps each leg only down to the `Foot` bone, with no foot volume, even though `skeleton_positions` has a `Toes` bone. The torso is a capped loft, so there is no crotch surface for a gusset to fit against. A stocking foot cannot be tested on today's bodies.
- **The shell only measures the torso outline for skirts.** In `wardrobe/engines/shell.py build_fitted_shell`, `torsoProfile` is computed only for `SKIRTED_KINDS`. `upperBody` (from `upper_body_surface`, a 1 cm front/back depth map covering chest to neck) and `lowerBody` (`lower_body_profile`: `crotchY`, leg sections every 3 cm) are computed for every garment. So bust and crotch landmarks can be derived from data the pipeline already has.
- **Hosiery already plugs in through hooks.** `wardrobe/engines/native.py` calls `hosiery_fit.before_shell / after_shell / after_bind / fit_connector`. Each hook is a no-op unless the garment has a `hosieryRole`. Lingerie should use the same pattern.
- **Hosiery strap tension is measured on the posed body.** `wardrobe/hosiery/suspender_straps.py taut_length` runs a string-pull over a posed body with its own skin weights. Its docstring explains that measuring the skinned garment vertices gave wrong results. `POSES = ("stand", "walk", "sit")`.
- **Templates are already versioned and can opt in.** `GarmentTemplate` has `schemaVersion` (`SCHEMA_VERSION = 1`) and `optIn`. Adding a new kind means updating `PROCEDURAL_KINDS` in `wardrobe/domain/garments.py` and `build_garment` in `procedural.py`. `tests/integration/test_hosiery_compat.py` re-checks gallery looks 1, 7, 8 and 19 against the hash baseline on every CI run.

## 1. Diagnosis

| Garment | Today | What the industry builds | Gap |
|---|---|---|---|
| Bra / bikini top | `_haul_sections.bra()`: one `build_band` tube from underbust to `bust_top`, widths from `half_at()`. Triangle cups are an edge re-cut by angle (`cups_profile`). | Two cups shaped on the bust apex, a centre gore tacked to the sternum, an underband along the fold under the bust, wings to the back closure, strap points on the cup peaks. | No bust landmarks. The band bridges straight across between the breasts. No separate panels or seams. |
| Briefs / bikini bottom | `briefs()`: a tube from `leg_opening` to `low_rise`, bottom edge lifted at the sides by `briefs_profile`. | Front panel, back panel and a lined gusset across the crotch. Leg-opening curves set by front rise, side height and back coverage. Waist and leg elastics. | An open tube with no crotch. The leg line is an angle function, not a curve on the body. |
| One-piece / bodysuit | `one_piece()`: one tube from `leg_opening` to `bust_top`. | Torso block with gusset and leg openings, bust shaping, neckline and back scoop. | Same as the two rows above. |
| Straps, ties, garter, harness | `sweep()` round cords, radius `_strap_radius` = max(0.4% of height, 4 mm), so about 7 mm thick. | Flat elastic 6–20 mm wide × about 1 mm thick, with anchors and a rest vs worn length. | Wrong cross-section. No anchors, no length, no tension. (`build_straps` does follow `upperBody`.) |
| Stockings / tights | `build_stockings` and `build_legwear` stop at the Foot bone plus 2% of height. | A foot with heel pocket and toe box. | No foot; the calibration body has no foot to fit either. |
| Elastic | `with_elastic` only renames edge triangle rows. | Elastic cut shorter than the edge (about 0.80–0.92×) with a known force for each stretch. | No length, no force, no pressure. |
| Materials | `finishes.py` and `textures`: alpha masks and blend opacity. | Separate physical specs (knit type, stretch, modulus, weight) and visual specs. | Visual only. Lace, fishnet and sheer share one vocabulary. |
| Validation | `FitReport.passed`: VRM validity plus clearance. | Garment-specific checks (see §5). | Clearance only. |
| Review body | `build_body_mesh`: 5 rings × 20 segments, cylinder legs. | Adult fit form with bust, waist, seat and feet. | Useless for judging lingerie fit. |

## 2. Architecture

```
 body landmarks (L1)          garment spec (template v2 "lingerie" block)
 upperBody/lowerBody/torso ─┐        │  BriefSpec / BraSpec / BodysuitSpec
 → BodyLandmarks            │        ▼
                            └──► PATTERN BLOCKS (wardrobe/lingerie/blocks/*)
                                 panels in (phi, y) body space → mapped onto measured surface
                                        │
                                        ▼
                                 SEWING RELATIONSHIPS  Seam(panel_a.edge, panel_b.edge, kind)
                                 (welded shared rows; length-match check)
                                        │
                                        ▼
                         FITTED CONTRACTS (after_bind, read back from the fitted mesh)
         FittedCup · FittedBand · FittedBrief · FittedElasticEdge · FittedStrap
         (all built on Anchor = generalized hosiery ClipPoint; FittedStockingTop unchanged)
                                        │
                                        ▼
                         ELASTIC TENSION (posed bodies stand/walk/sit, taut_length)
                         strain → force (ElasticSpec curve) → pressure (T / (r·w))
                                        │
                                        ▼
                         MATERIALS  FabricSpec (physical) ──derive──► VisualSpec (finishes/textures)
                                        │
                                        ▼
                         VALIDATION  wardrobe/lingerie/validate.py → FitReport.lingerie block
                                        │
                                        ▼
                         VRM export (existing assemble path; unchanged)
```

- **New package** `wardrobe/lingerie/`: `landmarks.py`, `contract.py`, `blocks/brief.py`, `blocks/bra.py`, `blocks/bodysuit.py`, `seams.py`, `straps.py`, `elastic.py`, `fit.py` (hooks), `report.py`, `validate.py`.
- **Dispatch.** A new `LINGERIE_KINDS = {"brief-block", "bra-block", "bikini-block", "bodysuit-block"}` is handled in `build_garment` before the `HAUL_KINDS` branch. `bra`, `briefs`, `bikini` and `one-piece` keep their current code paths exactly.
- **Hooks.** `native.py` calls `lingerie_fit.before_shell / after_bind` next to the hosiery hooks. Each returns immediately unless `artifact.metadata["lingerieBlock"]` is set.

## 3. Phases

The hash baseline stays untouched in every phase: v1 kinds and templates keep their code path, and `test_hosiery_compat.py` plus `geometry_hashes.py --check` must pass unchanged. New templates ship with `"schemaVersion": 2, "optIn": true`, so prompts that planned v1 templates still do.

### L1: Adult fashion-fit mannequin and body landmarks (M)

- **Goal:** a smooth, adult-proportioned, non-explicit fit form that makes lingerie fit reviewable, plus measured landmarks that every later phase uses.
- **Files:**
  - Add `wardrobe/vrm/fashion_body.py`: `FitFormProportions` (height, bust/underbust/waist/high-hip/full-hip girths, bust projection, seat projection, thigh girth, foot length), `FASHION_FIT_BODIES` (e.g. `fit-form-a-misses` roughly EU 38 / 75B, `fit-form-b-curvy` roughly EU 44 / 85D), and `build_fit_form_mesh()`.
  - The mesh is one loft of about 30 rings × 48 segments. Ring radius is `r(theta, y)`: a superellipse plus broad, low-frequency Gaussian lobes for bust and seat. Add a smooth closed crotch bridge and simple foot volumes along Foot → Toes.
  - Reuse `skeleton_positions` and the `build_vrm` flow; don't copy them.
  - Change `assets/calibration/policy.json`: add both names with `"depictsAdult": true` and update its `about` text.
  - Add `wardrobe/lingerie/landmarks.py`: `BodyLandmarks` (bust apex L/R, underbust fold y per side, sternum point, centre-front and centre-back lines, waist y from the narrowest `torso_profile` row, high hip, full hip, crotch point, side-seam line), derived from `upperBody`, `lowerBody` and `torso_profile()`.
  - Change `shell.py`: compute `torsoProfile` and `lingerieLandmarks` only when `kind in LINGERIE_KINDS`.
- **Tests** (`tests/unit/test_fashion_form.py`):
  - `declared_adult(name)` is true for each form.
  - The mesh is closed and valid (`mesh.validate()`).
  - Girths measured by `torso_profile` are within ±10 mm of the declared chart.
  - Smoothness: the largest discrete-curvature feature is at least 20 mm across, which enforces "no anatomical detail".
  - Landmarks are found on both forms and on `AvatarSample_A/B/C` and `fem_vroid`. If detection fails, fall back to formula landmarks and log a warning.
- **Compat:** `CALIBRATION_BODIES` and the gallery `BODY` are unchanged.

### L2: Flat ribbon straps with anchors and length (M)

- **Goal:** straps are flat ribbons that end on published anchors and carry a rest and a worn length.
- **Files:**
  - Move `ribbon()` from `suspender_straps.py` to `wardrobe/geometry/ribbon.py`, byte-identical, and re-export it from the old location.
  - Generalize `taut_length` into the same module.
  - Add `wardrobe/lingerie/contract.py`:
    - `Anchor(name, side, position, normal, tangent, u, v, vertex, bones, weights, source)`. This is `ClipPoint` generalized; `ClipPoint` stays as it is.
    - `StrapSpec(width_m=0.010, thickness_m=0.0012, elastic: ElasticSpec | None, adjustable: bool, slider_fraction)`.
    - `FittedStrap(name, front: Anchor, back: Anchor, path, rest_length, current: dict[pose, m], stretch: dict[pose, float])`.
  - Add `wardrobe/lingerie/straps.py`: the path comes from `_measured_strap` / `surface_point` (upperBody), normals from the depth map, and the mesh from `ribbon()`.
  - Add `FitPolicy.strap_profile: "" | "ribbon"`. It is only honoured by block kinds.
- **Tests:**
  - Ribbon thickness is ≤ 1.5 mm and width matches the spec ±0.5 mm.
  - Both ends are within 2 mm of their anchors.
  - Rest and current lengths are reported for all poses.
  - The strap sits outside the body with a gap of at least 0.5 mm.

### L3: Brief / bikini-bottom block (L)

- **Goal:** a real brief built from panels: front, back and gusset.
- **`BriefSpec` fields:** `rise` (front/back rise in mm from the waist landmark), `side_height_mm`, `front_coverage`, `back_coverage` (full | moderate | cheeky | thong), `gusset_width_mm` (front, crotch), `gusset_length_mm`, `leg_curve` (Bezier control fractions), `waist_elastic`, `leg_elastic`.
- **Construction:**
  - Panels live in `(phi, y)` body coordinates.
  - Above the crotch they map through `torso_profile`. The gusset maps through a small crotch depth map built like `upper_body_surface`, but from below.
  - The leg openings are curves in pattern space from the front-gusset corner through the side-height point to the back-gusset corner.
  - The panels are joined by a seam list `Seam(front.bottom, gusset.front, "overlock")` and similar.
- **Contract:** `FittedBrief(waist_ring, leg_openings{L,R}, gusset_seams, centre_front, centre_back, side_anchors{L,R})`. The side anchors are where hip ties and garter tabs attach.
- **Files:** `wardrobe/lingerie/blocks/brief.py`, `seams.py`, `fit.py`; `assets/garment_templates/underwear/under-briefs-v2.json`; `swim-bikini-bottom-v2`.
- **Tests (DoD):**
  - The mesh has exactly 3 boundary loops (waist and two leg openings) and one connected component.
  - Measured side height matches the spec ±5 mm.
  - The gusset centre is on the midline ±5 mm.
  - Seams are welded: shared vertex rows, and edge lengths match within 1%.
  - Clearance passes on both forms and on the 4 real avatars.

### L4: Bra block: cups, gore, underband, wings, strap anchors (L)

- **`BraSpec` fields:** `style` (triangle | balconette | plunge | full), `cup_height`, `neckline_point` (inner top), `strap_point` (cup peak), `gore_height_mm`, `gore_width_mm`, `underband_width_mm`, `wing_height_mm`, `closure` (back | front | none), `straps: StrapSpec`, `cup_ease_mm`.
- **Construction:**
  - Each cup is a grid in polar coordinates around the bust apex. It is mapped onto the `upperBody` front depth map plus ease, and its lower edge follows the fold under the bust.
  - The gore is mapped onto the sternum surface itself, not bridged.
  - The underband is a band at the fold under the bust built on `torso_profile` rings, with elastic along its bottom edge.
  - The wings run from the cup side seam to the closure.
  - Seams: cup → gore, cup → underband, cup → wing.
  - The triangle bikini top is `style="triangle"` with `underband_width_mm` about 8.
- **Contracts:**
  - `FittedCup(side, apex, outline, strap_anchor, neckline_point, wire_line)`.
  - `FittedBand(ring, closure_points, wing_anchors)`.
  - The strap anchors feed L2.
- **Tests:**
  - The apex projects inside the cup outline, at least 15 mm from the edge.
  - The gore is on the sternum: within 3 mm of the surface at x = 0.
  - The underband is level front to back ±10 mm.
  - Strap front anchors are on the cup peaks ±3 mm; back anchors are on the wing top.
  - Cups are symmetric ±5 mm.

### L5: Bodysuit / swimsuit block (M)

- **What it is:** the L3 lower block (gusset and leg openings) joined to a torso built from L4 landmarks: bust shaping by darts in `(phi, y)`, `neckline_profile` / `back_profile` reused as pattern-space curves, and an optional shelf bra.
- **Files:** `blocks/bodysuit.py`; `swim-one-piece-v2.json` and `under-bodysuit-v2.json`.
- **Tests:** all brief metrics; bust shaping keeps at least 5 mm clearance at the apex with no bridging, meaning the surface follows the depth map within ease + 5 mm between the apexes; boundary loops = neck/armholes + 2 legs.

### L6: Stockings and tights with feet (M)

- **Change:** add `foot: "none" | "full"` to `StockingPlan` in `wardrobe/hosiery/options.py`.
- **Default is `"none"` for now.** Switching the default to `"full"` later is a deliberate, separately reviewed re-baseline.
- **Construction:**
  - `build_stockings` continues the tube past `foot` along Foot → Toes, adds a heel pocket and closes the toe with a cap.
  - The foot is measured by a new `foot_profile()` in `geometry_checks.py`, modelled on `arm_profile`.
  - Tights get the same option through `build_legwear(..., foot=)`.
  - If the rig has no Toes bone, keep the old ending and record a report warning.
  - Fit the leg tubes to the measured leg sections (`lowerBody`, every 3 cm, as trousers and leggings already do), not the formula radius `hip_width × 0.2`.
- **Seen in the reference look:** light (taupe) thigh-highs on AvatarSample A show her skin at the inner left thigh, where her legs nearly touch. They also show her painted tights between the stocking end and her loafers. Black hid both. Rebuild `docs/images/red-dress.webp` with `tools/gallery/red_dress.py` as the regression picture.
- **Tests:** the foot is present with a closed toe; the heel is within 15 mm of the heel landmark; clearance on the fit forms; `FittedStockingTop` output is unchanged (band grip and clips identical).

### L7: Material models: physical separate from visual (M)

- **Physical spec.** Add `wardrobe/materials/fabrics.py`: `FabricSpec(name, construction: knit | woven | mesh | lace | net | elastic, weight_gsm, stretch_pct(warp, weft), modulus_n_per_m_at_10pct, recovery_pct, thickness_mm, lining: bool)`.
- **Starter library:** tricot, powermesh, stretch lace, galloon lace, tulle, fishnet (with hole size in mm), swim Lycra, cotton jersey (gusset lining), satin woven.
- **Visual spec.** `VisualSpec` is derived from the physical spec by `derive_visual()`:
  - **Sheer:** a continuous blend.
  - **Lace:** a motif alpha mask plus a scalloped edge.
  - **Fishnet:** a regular net whose tile size comes from the hole size and the body scale.
- **Panel defaults:** each block panel gets a default fabric. The gusset lining is always opaque; the cups are lined unless the spec says unlined.
- **Scope:** `finishes.py` and v1 paths are untouched.
- **Tests:** round trip from spec to visual; fishnet hole size ±10%; the gusset stays opaque under any sheer or lace request.

### L8: Elastic tension (M)

- **Data shapes:**
  - `ElasticSpec(width_mm, force_curve [(strain, N)], cut_ratio)`. Typical cut ratios: waist 0.90, leg 0.85–0.90, underband 0.80–0.85.
  - `FittedElasticEdge(name, ring, pattern_length, rest_length = cut_ratio × pattern_length, worn_length{pose}, strain{pose}, force_N{pose}, pressure_kPa{pose}, status)`.
- **Measurement:** the worn length is the posed-body circumference from `hosiery/poses.posed_body` plus `taut_length`, never from skinned garment vertices. Pressure = T / (r · w).
- **Poses:** `POSES` stays as it is. Add a `"reach"` (arms-up) pose only for strap and underband checks.
- **Tests:** strain and pressure reported for every edge and pose; thresholds in §5; strap stretch uses the same code path.

### L9: Garment-specific validation (M)

- **Files:**
  - `wardrobe/lingerie/validate.py`: per-type rule sets, each rule returning `{id, value, spec, status}`.
  - `wardrobe/lingerie/report.py`: builds `FitReport.lingerie: dict | None`, mirroring `hosiery` and `fit_garment.py` line 64.
- **Rollout:** violations go to `context.warn` first, as hosiery does. Promote them to `errors`, and so affect `passed`, only after tuning on the 4 real avatars plus 2 fit forms.
- **Previews:** `tools/gallery/lingerie.py`, modelled on `tools/gallery/hosiery.py`, renders stand/walk/sit only when `declared_adult(body)` is true.
- **Tests:** a job without the adult declaration is refused through the ordinary gate; the refusal test is not skipped.

**Order:** L1 → L2 → L3 → L4 → L5, with L6 in parallel after L1. L7 and L8 can start after L3 (they add numbers to the edges L3 already publishes). L9 grows with each phase.

## 4. Later phases (FashionProduct v2)

- **Pattern kernel** `wardrobe/patterns/`: 2D pieces with grainline, seam allowance and notches, plus a sewing graph. Generalize the L3–L5 `Seam` lists into it and flatten pieces from the fitted mesh.
- **POM and tolerances:** a points-of-measure table per product (e.g. waist relaxed/extended, leg opening, gusset width, cup height, underband), measured on the fitted mesh with ± tolerances. This replaces the ad-hoc checks in §5.
- **Grading by landmarks:** grade rules per POM across a size run, anchored on `BodyLandmarks`, and checked on both fit forms.
- **BOM and tech pack:** fabrics (L7), elastics (L8) and hardware (`hosiery/hardware.py`), exported as JSON, then PDF.
- **Template `schemaVersion 2` in general:** a `pattern` block required when schemaVersion is 2, enforced in `validate_semantics`, and a loader migration for v1.
- **Studio workspaces** (Design / Fit / Production), and platform work (Postgres repositories behind the existing `wardrobe/storage` interfaces).

## 5. Validation metrics (initial thresholds, tuned on the fit forms)

| Garment | Metric | Spec |
|---|---|---|
| Brief / bikini | Gusset connected | 1 component, 3 boundary loops |
| | Gusset on midline | ±5 mm; width = spec ±3 mm |
| | Leg-opening curve | side height ±5 mm; mean curve distance to spec ≤ 4 mm |
| | Front/back rise | ±5 mm from spec relative to waist landmark |
| | Waist elastic | strain 5–15% standing; pressure 0.4–1.5 kPa; no gaping (strain < −2%) in any pose |
| | Leg elastic | strain 3–12%; ≤ 1.5 kPa in sit |
| Bra / top | Apex inside cup | ≥ 15 mm from outline, both sides |
| | Gore on sternum | ≤ 3 mm from surface at x = 0 |
| | Underband level | ±10 mm front to back; strain 10–25% |
| | Strap anchors | front on cup peak ±3 mm; stretch ≤ 8% in reach, ≥ −5% in stand |
| | Symmetry | cups L/R ±5 mm |
| Bodysuit / swim | All brief metrics | as above |
| | No bust bridging | surface within ease + 5 mm of body between apexes |
| | Torso length | no vertical strain > 10% in sit |
| Stockings / tights | Foot present | closed toe, heel within 15 mm of landmark |
| | Band grip | clearance ≤ 2 mm, strain 5–15% at the band |
| | Clips | unchanged `FittedStockingTop` metrics |
| Straps (all) | Ribbon section | thickness ≤ 1.5 mm; ends ≤ 2 mm from anchors |
| All | Clearance | existing `clipping_check`; seams welded, length match ≤ 1% |

## 6. Risks and what not to do

- **Policy:**
  - Don't touch `wardrobe/policy/*`, `INTIMATE_CATEGORIES` or `requires_adult`.
  - Previews, tests and gallery always go through `declared_adult()` or the job's `depictsAdult`.
  - Never infer adulthood from mannequin geometry or measurements.
- **Mannequin:**
  - No anatomical detail. The smoothness test enforces this.
  - Generate it procedurally in-repo; no scanned or third-party meshes (licence).
  - Don't append it to `CALIBRATION_BODIES`.
- **Compatibility:**
  - Don't edit `build_band`, `half_at`, `cups_profile`, `briefs_profile`, `with_elastic`, `_strap_radius`, `build_straps` or the v1 templates.
  - Don't remove `optIn` from v2 templates or flip the stocking `foot` default without a separately reviewed hash re-baseline.
- **Physics:** no cloth simulation. Measure tension on posed bodies with `taut_length`, never on skinned garment vertices (the lesson recorded in `suspender_straps.py`).
- **Real avatars:** VRoid bust and crotch topology varies. Landmark detection must fall back to formula landmarks with a warning, not fail the job. Keep L9 rules as warnings until they are tuned on all 4 real avatars.
- **Scope:** don't start the pattern kernel, Postgres or Studio before L1–L5 land. Build seams and specs so they can be lifted into `wardrobe/patterns/` later, not a parallel system.
- **Performance:** posed-body sampling per elastic edge is costly. Cap sample counts as `taut_length` does (≤ 8000 points) and reuse the posed bodies once per job.

### Critical Files for Implementation
- wardrobe/geometry/procedural.py
- wardrobe/engines/shell.py
- wardrobe/vrm/build.py
- wardrobe/hosiery/suspender_straps.py
- wardrobe/hosiery/contract.py

Also relevant: `wardrobe/engines/native.py` (hook points), `wardrobe/engines/geometry_checks.py` (`torso_profile`, `upper_body_surface`, `lower_body_profile`), `wardrobe/domain/garments.py` (`FitPolicy`, `PROCEDURAL_KINDS`), `wardrobe/domain/looks.py` (`FitReport`), `assets/calibration/policy.json`, `tests/integration/test_hosiery_compat.py`.