# Body art (tattoos) plan

> Status: **proposed — nothing here is implemented.** Batches are `BA1`–`BA9`;
> commit subjects and code comments carry the prefix (`BA3: …`). Every file,
> function and number below was read or measured in this repository at
> `a0760eb`, the five library avatars included. Where this plan departs from
> the design brief it answers, section 2 says so and why.

Tattoos are **body-art decals**: a thin skinned patch that sits just above her
skin and carries a transparent ink texture. They are not garments. They are
never taken off with her clothes, they never take her clothes off, and they
never change what a garment is fitted to. Nothing is painted into the
avatar's own skin texture.

## 0. The rule this plan is built around

**Additive and non-destructive**, stated as properties a test can check:

| # | Invariant | How it is enforced |
|---|---|---|
| I1 | A job without `bodyArt` produces **the same bytes** it does today. | The stage returns before parsing anything when the list is empty; a golden test hashes the output of fixed jobs with and without the feature code present, and the gallery geometry hashes (`tests/fixtures/gallery_geometry_hashes.json`) must not move. |
| I2 | Body art only **appends**. Every node, mesh, material, texture, image, skin and accessor of the input is still there, unchanged, in the output. | A document diff test: the output's first *N* entries of every glTF array equal the input's. The one exception is I5. |
| I3 | The stored source is byte-identical after every job. | Already true and already tested (`test_the_stored_source_is_never_touched`); body art must keep it. |
| I4 | A decal is **never body and never clothing**. It is not in the garment inventory, never stripped, never sampled as skin by clearance, body-integrity or measurement. | An explicit `kind == "bodyArt"` skip in the three readers named in §1, tested by building on a look that carries a decal. |
| I5 | The only thing body art ever removes is **Forge body art**: an earlier decal at the same placement when a new one replaces it, or one the request removes by placement. | Removal selects nodes by `extras.wardrobeForge.kind == "bodyArt"` and nothing else. |
| I6 | A tattoo never exposes her. It is placed on her skin as it is; where her own clothes cover the placement, the tattoo is under them. | No body-art code calls the strip plan. "Check plan" says "covered by her tops" rather than taking them off. |
| I7 | Gated exactly like garments. A placement rated `swimwear` or `intimate` needs the model's own terms to allow it **and** an operator's declaration that the avatar depicts an adult. | The same `wardrobe.policy.intimate.evaluate` call the planner makes, before anything is built. |

## 1. What the code already gives us, and what it does not

Read before designing; each shapes a decision below.

- **The pipeline ends in bytes.** `wardrobe/pipeline/orchestrator.py execute`
  runs `validate_source → analyze_avatar → plan → prepare_base_body → generate
  → fit_garment → assemble_vrm → validate_output → render_preview`, and
  `assemble_vrm.run` leaves the finished VRM in `context.output_bytes` for
  *either* engine (native or Blender). A stage between `assemble_vrm` and
  `validate_output` therefore works for both engines and is checked by the
  existing output validation, without touching fitting.
- **The document can already carry textures.** `GltfDocument.add_image`,
  `add_texture`, `add_material`, `add_mesh`, `add_node`, `add_accessor`
  (`wardrobe/vrm/document.py`); PNGs are encoded without Pillow by
  `wardrobe/materials/png.py encode_png`, which the pattern textures use.
  `wardrobe/vrm/merge.py` registers VRM 0.x material properties
  (`_register_vrm0_material`), first-person annotations
  (`_register_first_person`) and borrows the avatar's own MToon shading
  (`borrow_toon_shading`) — all reusable for a decal material.
- **Garments are skinned by distance to bone segments** (`wardrobe/vrm/skinning.py
  bind_mesh`). That is right for cloth that stands off the body and wrong for
  ink, which must move *exactly* with the skin. Nothing in the repository
  transfers the body's own weights yet; `wardrobe/hosiery/poses.py` and
  `wardrobe/engines/geometry_checks.py` already *read* body `JOINTS_0` /
  `WEIGHTS_0`, so the reading half exists.
- **The inventory would ignore a decal already** — by luck, not by rule.
  `wardrobe/vrm/garment_inventory.py garment_inventory` recognises a Forge node
  only when `extras.wardrobeForge.kind == "garment"`, then falls back to the
  material-name patterns `_VROID` (`_Tops_01_CLOTH`) and `_FORGE`
  (`[Forge_Tops_01_CLOTH]`). A decal material named `[ForgeBodyArt] …` matches
  neither, so it is never a slot and never stripped.
- **Three readers would count a decal as her body.**
  `wardrobe/engines/geometry_checks.py body_points` reads every drawn mesh node
  (skipping only head-attached vertices and an explicit `skip` set);
  `wardrobe/vrm/body_integrity.py check_body` samples the body through it; and
  `wardrobe/hosiery/poses.py` (line 191) skips `kind == "garment"` nodes but
  would keep a decal. A decal 0.5 mm off the skin is harmless to clearance, but
  on a body with no skin under a garment it could fill a sector and make a
  hollow torso read as closed. I4 makes the skip explicit.
- **`OutfitRequest` fans out.** `wardrobe/pipeline/plan_outfit_stack.py` copies
  the request into every layer and set part with `model_copy` (lines 142–204).
  A `bodyArt` list inside `outfit` would be copied into each garment's request.
- **Unknown request fields are ignored, not refused.** `CreateJobRequest`,
  `OutfitRequest` and `JobOptions` are plain Pydantic models without
  `extra="forbid"`; an older server silently drops `bodyArt`. The Studio must
  therefore ask `/v1/capabilities` (`apps/api/main.py capabilities`) before it
  offers the section.
- **No identifier is derived from the request.** A pack look's `recipeId` is its
  look id (`apps/api/routes/studio.py:436`); nothing hashes the request, so a new
  field changes no existing id.
- **The chatbot drops unknown provenance.** `3D-Avatar-Chatbot
  src/wardrobe/WardrobePackValidator.js` (lines 207–242) rebuilds `provenance`
  from a field list; a new `provenance.bodyArt` is ignored there today, not
  rejected. Pack schema 2 can carry it; no version bump is needed to *carry* it.
- **Ratings already exist and can only hide.** `wardrobe/targets/pack.py
  rating_for(plan)` answers `general | swimwear | intimate` from the plan's
  gated garments.
- **The native preview cannot show a tattoo.** `wardrobe/geometry/raster.py`
  renders an orthographic *front* view with one flat colour per layer
  (`RenderLayer.color`), no textures. A back tattoo is invisible in it. The web
  preview backend (`JobOptions.preview_backend`, used by
  `wardrobe/hosiery/previews.py` for back views) is the one that can.
- **The five library avatars, measured:** each keeps her skin in a
  `*_Body_00_SKIN` primitive of a `Body` mesh with **zero morph targets**
  (the Face mesh has 54–57; no v1 placement is on the face). So a decal that
  copies the body's weights follows her exactly; no body morph can pull the
  skin out from under it on these files.
- **The chatbot's camera** is `PerspectiveCamera(30, aspect, 0.01, 100)`
  (`src/gltf-viewer/ViewerEngine.js:49`). With a 24-bit depth buffer that
  resolves ≈ 0.02 mm at 2 m and ≈ 0.6 mm at 10 m: a 0.5 mm offset does not
  flicker at any distance she is viewed from.

## 2. Where this departs from the brief, and why

1. **`bodyArt` is a sibling of `outfit` on the job, not a field inside it.**
   Inside `outfit` it would be copied into every layer by `model_copy` (§1). At
   the top level it is read once, and a body-art-only job (BA6) is just a
   request whose `outfit` is absent.
2. **The decal shares the body's own skin.** The decal node references the
   *same* `skin` index as the body mesh node, and each decal vertex gets the
   barycentric blend of the three body vertices under it (top four joints,
   renormalised). No new joints, no new inverse bind matrices: "skeleton kept"
   holds by construction, and the decal deforms exactly like the triangle it
   sits on. `bind_mesh` is not used.
3. **The stage runs after `assemble_vrm`, on the output bytes.** Not inside the
   native engine, so the Blender engine gets it too, and never before fitting,
   so it cannot influence clearance, measurement or the strip plan.
4. **v1 designs are authored in the repository as vector paths**, rasterised
   by our own code into PNGs at build time: Apache-2.0 by construction,
   deterministic (a test pins their hashes), no external API in the path.
   Concept art made with an image model can come in later through an install
   tool that records provenance and refuses a PNG without a real alpha channel
   (BA4), the way the chatbot's ambience plates did.
5. **Rating belongs to the design *at a placement*,** using the three ratings
   packs already have, so nothing downstream learns a new word (§5).
6. **No pack schema bump to carry the recipe.** `provenance.bodyArt` is additive
   and ignored by the chatbot today (§1). Showing it in Try-On is a separate,
   later chatbot change.

## 3. Architecture

```
CreateJobRequest
  avatar, outfit, options          (unchanged)
  bodyArt: [BodyArtRequest]        (new, default [])
  bodyArtRemove: [placement]       (new, default [])

            plan ──► … ──► assemble_vrm ──► APPLY BODY ART ──► validate_output ──► render_preview
                                              │
                          empty? ─────────────┴─► return (no parse, same bytes)  [I1]
                          otherwise:
                            gate every item (plan-time check already refused)    [I7]
                            parse output → find skin → resolve placement frame
                            cast grid onto skin → offset → copy weights
                            add image/texture/material/mesh/node, tagged         [I2]
                            record in fit report + root provenance
                            re-serialise; size limit re-checked
```

### Data model

```python
class BodyArtRequest(BaseModel):          # wardrobe/body_art/contract.py
    design: str                           # catalogue id, e.g. "tribal-wings-01"
    placement: str                        # "upper-back", "spine-full", …
    scale: float = 1.0                    # 0.5–1.5 of the placement's default size
    offset_u: float = 0.0                 # −0.25…0.25 of the placement width
    offset_v: float = 0.0                 # −0.25…0.25 of the placement height
    rotation: float = 0.0                 # degrees, −30…30
    opacity: float = 0.9                  # 0.3–1.0
    ink: str = "#141414"                  # sRGB hex; tint mode only
    mirror: bool = False
```

Catalogue entry (`assets/body_art/body-art.json`, one file, validated like
`TemplateCatalog`):

```json
{
  "id": "tribal-wings-01",
  "name": "Tribal Wings",
  "family": "upper-back-tribal",
  "placements": ["upper-back"],
  "aspect": 2.4,
  "inkMode": "tint",
  "source": "vector",
  "paths": "designs/tribal-wings-01.json",
  "license": "Apache-2.0",
  "rating": {}
}
```

`rating` is an override map `{placement: rating}`; absent, the placement's own
rating applies (§5). A design can only raise a rating, never lower it.

Placement (code, `wardrobe/body_art/placement.py`): a named frame built from
`BodyMeasurements.bone_positions` and the avatar's facing (the same `forward`
the hosiery poses use): an axis (the spine for torso placements, the thigh bone
for thigh ones), a centre height between two bones, an angular span or a
width, a facing used by the Studio to turn the viewer, the body region it lies
in (`upper`/`lower`, for "covered by" reporting) and a rating.

### Projection (`wardrobe/body_art/project.py`, pure numpy)

1. **Find her skin.** The primitives of mesh nodes that are skinned, not
   head-attached, not in the garment inventory, not Forge-tagged (garment or
   body art). On the five library avatars this is exactly the
   `*_Body_00_SKIN` primitive. No skin found in the placement's box → the item
   is skipped with a reason (fail soft), the rest of the look is delivered.
2. **Build the grid in the placement frame**: *u* around the axis (arc length),
   *v* along it; ~48×24 quads for the upper back.
3. **Cast** each grid point inward toward the axis against the skin triangles
   inside the placement's bounding box; keep the first hit, its triangle and
   barycentrics. Fewer than 98 % hits → the placement does not fit this body;
   skip with a reason.
4. **Offset** each hit 0.5 mm along the interpolated vertex normal.
5. **Weights**: blend the three vertices' `(joint, weight)` sets by the
   barycentrics, keep the four largest, renormalise.
6. **UVs** are the grid's own (0–1 across the design), so the ink texture maps
   directly; the avatar's UV layout is never read or written.
7. **Measure stretch**: per triangle, 3D area over UV area against the median.
   Worse than 1.35 → skip with a reason.

### Material (`wardrobe/body_art/materials.py`)

MToon, named `[ForgeBodyArt] <design>` (matches neither inventory pattern).
Shading borrowed from her skin material (`borrow_toon_shading`) so the ink is
lit like her skin. Alpha `BLEND`, single-sided, no z-write for transparency.
The render queue sits one step above the skin: VRM 0.x `renderQueue`, VRM 1.0
MToon `renderQueueOffsetNumber`. `inkMode: tint` multiplies an alpha-only
texture by the ink colour. One image per design, shared when two items use the
same design.

### The node's tag

```json
"extras": { "wardrobeForge": { "kind": "bodyArt", "design": "tribal-wings-01",
  "placement": "upper-back", "rating": "general", "version": 1 } }
```

The document root's existing `extras.wardrobeForge` (written by
`merge.tag_derived`) gains `"bodyArt": [ … the requests as applied … ]`.

### Lifecycle

| Action | Result |
|---|---|
| New garment on a look that has a tattoo ("Build on") | The tattoo stays: the inventory does not see it (I4). |
| New tattoo at a placement already inked | The old Forge decal at that placement is removed, the new one added (I5). |
| `bodyArtRemove: ["upper-back"]` | Removes the Forge decal at that placement and nothing else. |
| Restore the original avatar (chatbot) | The original has no decals; the look was a derived file. |

## 4. Phases

Sizes follow the lingerie plan: S ≈ a day, M ≈ a few, L ≈ a week.

### BA1: Contract and catalogue, no pipeline change (S)

- `wardrobe/body_art/{__init__,contract,catalog}.py`; `assets/body_art/body-art.json`.
- `CreateJobRequest.body_art` / `body_art_remove` (aliases `bodyArt`,
  `bodyArtRemove`), default empty; Pydantic bounds on every number; at most
  one item per placement; at most 4 items.
- `GET /v1/body-art` lists designs and placements; `/v1/capabilities` gains
  `bodyArt: {version: 1, placements: [...]}`.
- **Exit:** full suite green with *no* test changed; I1 golden test added and
  passing (nothing reads the field yet).

### BA2: Placements and projection as pure functions (M)

- `placement.py`, `project.py`; v1 placements: `upper-back`, `spine-upper`,
  `spine-full`, `lower-back`, `nape`, `left-shoulder-blade`,
  `right-shoulder-blade`.
- Tests on the calibration bodies and the fashion-fit forms (declared adult,
  `assets/calibration/policy.json`) and on the dress form
  (`tests/integration/test_dress_form.py`, a real VRoid topology): hit rate,
  stretch, symmetric left/right, offset envelope in the rest pose.
- **Exit:** every v1 placement projects onto all six generated bodies and the
  dress form within the §6 thresholds.

### BA3: The stage, and "never body, never clothing" (M)

- `wardrobe/pipeline/apply_body_art.py`, called between `assemble_vrm` and
  `validate_output`; early return on an empty list (I1).
- The explicit skips of I4 in `geometry_checks.body_points`,
  `body_integrity.check_body` (through `body_points`) and `hosiery/poses.py`.
- Fit report `bodyArt: [{design, placement, applied, reason?, hitRate,
  maxStretch, weightsValid}]`; root provenance.
- **Exit:** I2 document-diff test; I4 test (build a dress on a look with a
  tattoo: inventory, strip plan and body integrity identical to the same body
  without it); `validate_output` passes the decal's weights.

### BA4: Designs, material and a preview that shows them (M)

- Six upper-back presets as vector paths (`assets/body_art/designs/*.json`):
  winged tribal, V-shaped shoulder-blade tribal, central-spine tribal with side
  flourishes, curved geometric bands, thorn filigree, lace-like ornament; plus
  one each for spine, lower back and nape. A rasteriser
  (`wardrobe/body_art/raster.py`, supersampled scanline fill, numpy) and a
  hash test pinning every PNG.
- `tools/body_art/install_design.py` for raster art from elsewhere: PNG only,
  real alpha required, size and dimension limits, re-encoded, provenance
  written beside it (model, prompt, date, licence).
- Body-art looks render their thumbnail from the **back** view through the
  web preview backend; without it, the report says the tattoo is not visible
  in the front thumbnail.
- **Exit:** golden back-view previews on the calibration mannequin; a
  pose-sweep test (§6) on every preset.

### BA5: Studio (M)

- A collapsed **Body art · optional** section, shown only when
  `/v1/capabilities` has `bodyArt`. Master choice `None | Tattoo`; placement
  select; design tiles (thumbnails from the catalogue); ink, size, offsets,
  rotation, opacity, mirror; Remove.
- Choosing a placement turns the viewer to its facing (back three-quarter for
  `upper-back`).
- "Check plan" lists each tattoo with its rating and gate, and says "covered by
  her tops" or "partly under her hair" instead of changing anything (I6). Long
  VRoid hair covers the upper back; head-attached points behind the patch are
  what tells.
- **Exit:** the §7 Studio checks in a browser.

### BA6: Lifecycle and body-art-only jobs (M)

- Replace by placement and `bodyArtRemove` (I5), on a look used as the base.
- `outfit` becomes optional **only** when `bodyArt` or `bodyArtRemove` is
  non-empty; that job runs `validate_source → analyze_avatar → apply_body_art
  → validate_output → render_preview` and writes the source document through
  the same exporter. A request with neither is a 422, as today.
- **Exit:** tattoo → dress → second tattoo elsewhere → remove the first: each
  step's document diff contains only what that step asked for.

### BA7: Packs and the chatbot (S)

- `rating_for` takes the stronger of the garments' rating and the body art's.
- `provenance.bodyArt` in the pack manifest and `look.json`.
- A chatbot test that imports a pack whose looks carry `provenance.bodyArt`
  and checks it validates unchanged (the field dropped, the look listed).
  Surfacing it in Try-On is a later chatbot W-batch.
- **Exit:** a body-art look round-trips Forge export → chatbot import.

### BA8: Placements that go under clothes (M)

- `left-hip`, `right-hip`, `left-rib`, `right-rib` (rated `swimwear`);
  `sternum`, `under-bust`, `left-upper-thigh`, `right-upper-thigh` (rated
  `intimate`); `left-outer-thigh`, `right-outer-thigh` (`general`).
- Thigh placements use the thigh axis; they are the first to bend at the hip,
  so the pose sweep includes `sit` and a forward bend.
- Multiple tattoos in the Studio (the contract allowed four from BA1).
- **Exit:** gated placements refused on an undeclared avatar before anything is
  built; pose sweep within thresholds on the fit forms.

### BA9: Custom tattoo import (M, last)

- Admin session only; looks made with an imported tattoo are private
  (`JobOptions.private`) and excluded from public exports.
- PNG or WebP upload, decoded with Pillow under limits (2048×2048, 4 MB,
  decoded-pixel cap), real alpha required, re-encoded (drops metadata), stored
  under the job, never fetched from a URL, never SVG.
- **Exit:** malformed, oversized and alpha-less files refused with reasons;
  nothing imported appears to a guest.

## 5. Ratings and gates

| Placement | Rating | Why |
|---|---|---|
| `nape`, `upper-back`, `left/right-shoulder-blade`, `spine-upper`, `spine-full`, `lower-back`, `left/right-outer-thigh` | `general` | Seen in everyday clothes: a backless top, a crop top, shorts. |
| `left/right-hip`, `left/right-rib` | `swimwear` | Seen in swimwear. |
| `sternum`, `under-bust`, `left/right-upper-thigh` | `intimate` | Seen only in lingerie or less. |

- Gating reuses `intimate.evaluate` exactly as `generate_garment.plan` does,
  with the model's own terms checked first (a VRM that disallows sexual use
  refuses `swimwear`/`intimate` placements whatever the declaration) and the
  operator's declaration second. Adulthood is never inferred from how an avatar
  looks.
- A general-rated tattoo on an avatar nobody declared is ordinary styling and is
  allowed where the licence allows modification — which `validate_source`
  already checks for every job.
- Showcase and golden renders of `swimwear`/`intimate` placements use the
  calibration bodies and fit forms only, declared by
  `assets/calibration/policy.json`. Library characters appear only with
  `general` placements.
- Design names are descriptive ("Tribal Wings", "Thorn Filigree"). v1 has no
  text, no lettering and no likenesses; BA9 imports are the operator's own,
  private, and admin-only.

## 6. Validation metrics (initial thresholds, tuned in BA2)

| Metric | Threshold |
|---|---|
| Grid rays that hit her skin | ≥ 98 % |
| Distance from the posed skin, every decal vertex, in `stand`, `walk`, `sit` (`hosiery/poses.py`), `POSE_TESTS`' `arms-down` and `legs-apart`, and an **arms-raised** pose added for body art only | 0.5 mm ± 0.3 mm |
| Triangle stretch (3D area / UV area, over the median) | ≤ 1.35 |
| Weights | sum 1 ± 1e-3; every joint in the body's own skin |
| Detached vertices / components | 0 / 1 per decal |
| Output size | still under `settings.max_output_bytes` |

`POSE_TESTS` has no raised-arm pose, and raised arms are what moves the
shoulder blades under an upper-back tattoo. It is added in
`wardrobe/body_art/`, not to `POSE_TESTS`: that table feeds every fit report,
and `hosiery/poses.py` already documents why it is not edited.

Because the decal copies the weights of the triangle under it, the posed
distance is exact at the three body vertices and deviates only by linear
blending between them. A failure here means a projection bug, not a skinning
limitation.

## 7. Risks, and what not to do

- **Do not paint into her skin texture.** The UV layout is the avatar's; the
  texture may be shared with the face; the change would be destructive and
  unrecoverable.
- **Do not route body art through garments**: not a template, not a
  `KIND_REGIONS` kind, not a slot, not a foundation. A tattoo must never appear
  in a strip plan.
- **Do not take clothes off to show a tattoo** (I6).
- **Morph targets.** None on the five avatars' body meshes; an uploaded avatar
  may have them. A placement whose triangles move under a body morph is skipped
  with a reason until morph copying is designed.
- **Hair.** Long hair hides the upper back in the rest pose; the Studio says so
  rather than moving hair.
- **Transparency sorting.** One decal per placement, queue above skin, no
  z-write; verified in the chatbot's three-vrm viewer, not only in the Forge
  preview.
- **The native preview cannot show it** (§1): do not report a body-art look's
  preview as showing the tattoo unless the back view rendered.
- **Studio check (BA5).**
  - The section is absent when `bodyArt` is not in `/v1/capabilities`.
  - A general placement on a library avatar builds.
  - An intimate placement on an undeclared avatar is refused in Check plan.
  - Building a dress on a tattooed look keeps the tattoo.

### Files

New: `wardrobe/body_art/{__init__,contract,catalog,placement,project,materials,raster}.py`,
`wardrobe/pipeline/apply_body_art.py`, `assets/body_art/body-art.json`,
`assets/body_art/designs/*.json`, `tools/body_art/install_design.py`,
`tests/unit/test_body_art_{catalog,placement,projection,raster}.py`,
`tests/integration/test_body_art_{pipeline,lifecycle,pack}.py`.

Changed: `wardrobe/domain/jobs.py` (`CreateJobRequest`),
`wardrobe/domain/looks.py` (`FitReport.body_art`),
`wardrobe/pipeline/orchestrator.py` (one call; BA6's optional-outfit path),
`wardrobe/engines/geometry_checks.py` and `wardrobe/hosiery/poses.py` (I4),
`wardrobe/targets/pack.py` (`rating_for`, provenance), `apps/api/main.py`
(capability), `apps/api/routes/studio.py` (Check plan, catalogue route),
`apps/studio/{index.html,js/app.js,studio.css}`.

Not changed: `wardrobe/domain/garments.py`, `wardrobe/vrm/garments.py`
(`KIND_REGIONS`), `wardrobe/vrm/garment_inventory.py`,
`wardrobe/pipeline/prepare_base_body.py`, every garment template.
