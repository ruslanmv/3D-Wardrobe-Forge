# Body surface — a collision body, regions as morph targets, and XPBD

The body-surface subsystem (batches **BS0–BS6**) gives a job a better body to fit
to, and optionally a changed body surface to export, **without turning the
garment fitter into an anatomy generator**. It sits between Base Body Prep and
garment generation, is **off unless a job asks for it**, and is reached only
through server-side, allowlisted, provenance-checked profiles.

This document is grounded in the code on this branch. Every number in it was
measured here, and every "not built" is stated as such.

## The rule this was built under

**Nothing that existed changes.** A job without `bodySurface` reads her body
exactly as before, fits exactly as before and reports exactly as before (no
`bodySurface` block, no `relaxation` entry). The proof is the strongest test the
repository has: all **81** gallery looks (21 mannequin looks, and 15 everyday
looks on each of four real avatars) were rebuilt on this branch and compared
garment by garment — geometry, normals, UVs, skin weights and material — with
the same looks built from `main`: **81/81 identical**.

(The committed baseline `tests/fixtures/gallery_geometry_hashes.json` differs
from `main` itself on three lingerie looks — mannequin/03, /04, /09 — because
it predates `main`'s gusset material work. Those three are byte-identical
between `main` and this branch; the comparison above is against `main`'s own
output.)

## Where it sits

```
validate_source → analyze_avatar → plan → prepare_base_body → set_stance
    → prepare_body_surface   (BS1–BS3: only when the job has bodySurface)
    → generate_garment → fit_garment (+ BS5 relaxation, BS2 clearance) → assemble_vrm (+ BS3 export)
```

| Piece | Path |
| --- | --- |
| Request vocabulary (`bodySurface`, capabilities, mask policy) | `wardrobe/body_surface/contract.py` |
| Allowlist: profiles, templates, provenance, computed capability | `wardrobe/body_surface/library.py` |
| The gate (model terms → operator switch → declaration) | `wardrobe/body_surface/gate.py` |
| Her skin per POSITION buffer | `wardrobe/body_surface/surface.py` |
| Anchors from measured landmarks | `wardrobe/body_surface/anchors.py` |
| Regions as morph targets | `wardrobe/body_surface/regions.py` |
| Collision body, state, signed clearance | `wardrobe/body_surface/collision.py` |
| glTF morph export | `wardrobe/body_surface/export.py` |
| XPBD relaxation | `wardrobe/body_surface/xpbd.py` |
| Material-aware masking policy | `wardrobe/body_surface/masking.py` |
| Mesh mathematics (NumPy only) | `wardrobe/body_surface/geometry.py` |
| Stage | `wardrobe/pipeline/prepare_body_surface.py` |
| Template installer | `tools/body_surface/install_template.py` |
| Shipped profiles and templates | `assets/body_surface/` |
| `GET /v1/body-surface/profiles` | `apps/api/routes/body_surface.py` |

Changes to existing code are small and each is a no-op without a body surface:
`body_points(…, positions=None)` gains an optional override;
`shell.build_fitted_shell` passes the collision body to it when there is one;
`fit_garment` adds a relaxation call and a clearance block behind the same
check; `assemble_vrm` exports morphs only at `detailLevel: "render"`; the
Blender engine's `mask_policy` now delegates to `masking.py` and returns
exactly what it returned before (checked over every alpha mode and opacity).

## Asking for it

```json
{
  "avatar": { "storageKey": "…", "depictsAdult": true },
  "outfit": { "prompt": "black tailored briefs" },
  "bodySurface": { "profileId": "collision-close-fit", "detailLevel": "garment-fitting" },
  "options": { "clothRelaxation": "xpbd" }
}
```

- `bodySurface.profileId` — an id from `GET /v1/body-surface/profiles`, never a
  path, URL or template (the pattern refuses them; extra fields are refused).
- `detailLevel` — `garment-fitting` (default): the surface is built, fitted to
  and reported; **nothing about her body is exported**. `render`: made regions
  are also exported as morph targets.
- `options.clothRelaxation` — `none` (default) or `xpbd`. Without a body surface
  it does nothing: there is nothing to relax against.

The Studio does not offer any of this. A body surface is an API capability; the
public gallery and the Studio keep garment-covered rendering.

## Who may have one

Profiles carry one of three capabilities, **computed** from their regions — a
profile file can raise its capability, never lower it:

| Capability | What it is | Gate |
| --- | --- | --- |
| `body_collision` | a collision body only; nothing about her looks different | none beyond the licence stage |
| `body_surface` | regions that are not intimate (the navel) | the licence stage's modification check, as for any garment |
| `adult_body_surface` | any region in `INTIMATE_REGIONS` | the three questions below, in order |

For the adult capability, the first "no" wins:

1. **The model's own terms.** VRM 0.x `sexualUssageName: Disallow` **and**
   VRM 1.0 `allowExcessivelySexualUsage: false` both refuse. (A swimsuit reads
   VRM 1.0's flag leniently, because a swimsuit is not sexual expression; a
   visible anatomical surface may be, so here the author's `false` is a no.)
2. **The operator's switch** `WARDROBE_ADULT_BODY_SURFACE`, off by default.
3. **The adult declaration** for this avatar — from the server for the library
   and admin sessions, attested by the caller for an upload, never from a
   prompt. Age is never inferred.

Refusals are `rejected` jobs with `body_surface_not_permitted` (or
`body_surface_profile_unavailable` for an unknown profile), before anything is
built.

## Templates, licences and provenance

A template is a displacement field `(dn, du, dv)` in metres over a square chart
in her local tangent frame (u across her, v up her), zero on the chart's edge,
with chart landmarks that can bind to measured body landmarks. It enters the
allowlist only through `tools/body_surface/install_template.py`, which:

- refuses any licence not on `LICENSES` (CC0-1.0, CC-BY-4.0, MIT, Apache-2.0, or
  `LicenseRef-Commissioned` for an asset under agreement). **SMPL, SMPL-X and
  STAR model data are research-only and are deliberately not on the list**;
- refuses a template without `--no-real-person-scan`: a scan of a real person is
  biometric data (GDPR Art. 9) and needs consent and review this tool cannot
  record;
- records the field's SHA-256; the server re-hashes on every load and refuses a
  template edited afterwards — and any profile that needs it.

**What ships:** two collision-only profiles and one navel profile, whose
template (`navel/v1`) is an analytic dimple authored in the installer itself
(`procedural_navel`), CC0. **No intimate template ships, and none was authored
for this branch.** The adult path is built and tested end to end with a
test-only generic bump labelled as an intimate region; a deployment that wants
anatomical regions installs licensed templates (for example derived from
MakeHuman's or Blender's CC0 base assets, or commissioned) through the
installer, turns the operator switch on, and serves only declared avatars.

`GET /v1/body-surface/profiles` lists ids, titles, capabilities and region
names. Templates, fields, paths and provenance never leave the server, and are
never written into an exported VRM.

## The collision body (BS2)

Her skin is read per POSITION buffer (`surface.skin_parts`): chosen by material,
not texture (so calibration bodies and fit forms have one), without her own
clothes, Forge garments, tattoos, or anything that moves with her head. Then,
**on the welded mesh** (see below):

- each region contributes only its `collisionDetail` share (the navel 0.1: cloth
  bridges a navel, it does not dip into it);
- Taubin λ|μ smoothing removes detail below `detailCutoffMm` without shrinking
  her; on a VRoid torso (13–19 mm edges) a 3 mm cutoff smooths nothing — the
  mesh holds no detail that fine — and the report says `smoothingPasses: 0`;
- a vertex only ever moves **outward** along its normal, plus `outwardMarginMm`:
  the collision body always contains the render body.

The fitter reads it in place of her stored skin (`body_points(positions=…)`),
so every rule `body_points` applies — head exclusion, alpha-cut skin — applies
to it unchanged. `collision-close-fit` also sets `closeFitClearanceMm: 1.5` for
lingerie and swimwear blocks on bare skin: the bikini top on VRoid Female moved
from 1.9 mm to 0.9 mm off her skin with **no sample inside her**.

**Seams are welded.** Skins keep two copies of every vertex on a seam (UV seams;
the fit form's midline). Treated separately, each copy's normal sees one side:
offset along them, the copies parted and the collision body opened a 2 mm crack
down the fit form's crotch midline. Everything that reads neighbourhoods —
normals, smoothing, geodesics, the smooth-normal field — works on the welded
mesh and gives the result back to every copy; the tests check that no seam
opens in either the envelope or a region.

## Signed clearance (BS2)

With a body surface, the fit report carries, per layer, the signed distance
from her **render** body (what would show) of the garment's vertices, edge
midpoints and face samples (8 mm): the minimum, the mean penetration, the count
and share below −0.5 mm and −1 mm. One minimum is not enough — one numerical
speck and a palm-sized patch through her have the same minimum.

The sign is taken from the **smooth normal at the closest point**, not the
closest face's own normal: below a crease the closest point is the crease edge,
either face may win the tie, and a face normal points across the gap. Where a
penetrating sample has surface of both signs within 1.5 mm (a narrow hollow),
it is counted in `uncertainPenetratingSamples` rather than trusted silently.

**What it found.** The black tailored briefs on the declared adult fit form, as
fitted by `main`: every vertex at least 1.55 mm clear, but **36 samples (0.2%)
up to 1.85 mm inside her**, all on the gusset's centre line under the crotch —
flat faces cutting a chord through a curve between vertices that clear. The
existing fitter leaves a pattern block's gusset to the block, so its own checks
never sampled those faces. Nothing on this branch changes that fit; it is
reported here as a finding for the lingerie work.

## Regions as morph targets (BS3)

For each region, on each buffer (all on the welded mesh):

1. **Anchor** from her measured landmarks (`lingerie.landmarks` — waist, hips,
   crotch, sternum, bust points, centre front) and nothing else: never a name, a
   prompt, her clothes or a guessed gender. The navel is put on her centre-front
   line 30% of the way from her natural waist to her high hip.
2. **Support** — her vertices within the template radius *along her surface*
   (Dijkstra geodesic), scaled by her waist width against the template's.
3. **Registration** — her chart (tangent frame at the anchor) is mapped into the
   template's by a 2-D RBF warp (Wendland C² kernel with an affine part) through
   the landmark pairs; the residual is reported.
4. **Field** — `(dn, du, dv)` sampled bilinearly, expressed in her own normal and
   chart axes, times a Wendland mask of geodesic distance.
5. **Blend** — `argmin ‖Δ−Δ₀‖² + λ‖LΔ‖²` with everything outside the support held
   at zero, by conjugate gradients: no step at the edge.
6. **Checks** — fewer than 8 of her vertices in the support and the region is
   not made (*"finer detail belongs in a normal map"*); a change of more than
   0.5% to a measurement it promised to preserve and it is dropped, so a detail
   can never change the size her garments are made at.

At `render`, made regions are appended to her body mesh as ordinary glTF morph
targets: same count as the POSITION they morph, `min`/`max` set, the same
number of targets on every primitive of the mesh (VRoid draws skin, tops and
shoes from one buffer), existing targets keep their indices (so expressions
bound to them still work), default weights in `mesh.weights`, names in
`extras.targetNames`. Her POSITION data is never modified; no bone is added.
The Blender engine writes its VRM from its own copy of the source, so it does
not carry them — the report says so rather than claiming them.

**What her mesh can hold.** Measured on the library: VRoid skins have median
edges of 13–19 mm (AvatarSample A/B 13.4, fem_vroid 14.3, Rinna 19.3). The
navel's hollow is about 8 mm across inside a 36 mm support; on VRoid Female
that support holds 7 vertices after scaling, and the region is refused with
the reason. On the fit form (12 mm edges) it is made: 13 vertices, a 1.7 mm
hollow, every measurement unchanged to 0.0%. **Same-topology morphs can express
regions several edges across, not detail smaller than an edge** — that is a
normal-map job, or a denser mesh from an offline path (below).

## Cloth relaxation (BS5)

Quasi-static XPBD on the welded garment: per-edge stretch and isometric bending
constraints at the fitted lengths with compliance, and an inequality contact
constraint against the collision body (1 mm cloth thickness) at vertices **and**
face samples and edge midpoints, a face point's correction shared by its corners
in proportion to its barycentrics. On a test sphere it takes a garment dented
5 mm into the body to +0.94 mm with at most 9% edge strain.

**A relaxation is kept only if it made her render-body clearance no worse.**
On the fit form's briefs it is not: the gusset sits in the hollow below her
crotch, where the nearest surface can be either wall and a contact push can go
the wrong way. The report records the relaxation, `applied: false` and why, and
the garment is kept exactly as fitted (the integration test compares its
positions).

## Masking (BS4)

`masking.body_mask_policy` names the three cases by **material**: blended or
sub-opaque fabric → `never`; alpha-masked (lace, fishnet) → `alpha-aware`;
opaque → `opaque-only`. The Blender worker knows `none` and `body-only`, and
cannot test a lace texture's holes per body polygon, so alpha-aware is sent as
`none` — the engine's existing behaviour, now with its reason written down.

## Not built

Stated plainly, from the design this branch was asked to start:

- **No statistical shape model.** A PCA body space needs licensed training data;
  SMPL/SMPL-X/STAR are research-only. Her macro shape is her own mesh.
- **No pose-space correctives, no pose stress suite for the body surface.** The
  fitter still fits one rest pose; the existing `poseTests` are unchanged.
- **No normal / displacement map baking**, so detail finer than her mesh is not
  represented anywhere.
- **No offline Blender stitching / remeshing path** for templates that need
  more vertices than her mesh has.
- **No dynamic cloth**: no gravity, velocity, CCD, self-collision, FEM,
  anisotropic fabric or adaptive remeshing. XPBD here is a static relaxation.
- **No LOD**.
- **No alpha-aware masking in the Blender worker** (it is conservative instead).
- **No Studio UI**, deliberately.
- **No intimate templates**, deliberately (see *Templates*).

## Tests

- `tests/unit/test_body_surface.py` — 45 tests: geometry, allowlist and
  provenance, capability computation, request validation, the gate in order,
  regions (made, supported, measured, seamless, refused when too coarse), the
  collision body containing her, export validity, XPBD, masking, and
  `body_points` unchanged without an override.
- `tests/integration/test_body_surface_jobs.py` — 10 jobs: nothing added
  without it, unknown profile refused, the adult gate refusing in order and
  running with all three, collision-only fit with clearance and nothing
  exported, render export with her positions unchanged, the relaxation guard.
- `tools/gallery/geometry_hashes.py` — the 81-look comparison above.
