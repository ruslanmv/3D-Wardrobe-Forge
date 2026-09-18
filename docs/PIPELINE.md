# The pipeline

Ten stages, in this order. Each emits a state the client can display.

```
validating → analyzing-avatar → planning-outfit → generating-garment
   → fitting → skinning → resolving-clipping → exporting
   → validating-output → rendering-preview → completed
```

| # | Stage | Module | Does |
| --- | --- | --- | --- |
| 1 | validate source | `validate_source.py` | fetch, size/hash/format checks, licence gate |
| 2 | analyze avatar | `analyze_avatar.py` | humanoid validation, body measurement |
| 3 | plan outfit | `plan_outfit.py` | prompt → category/silhouette/hem/fabric/colour → template |
| 4 | generate garment | `generate_garment.py` | provider produces the garment artifact |
| 5–7 | fit / skin / clip | `fit_garment.py` → engine | build shell, de-intersect, bind weights |
| 8 | assemble | `assemble_vrm.py` → engine | write the derived VRM |
| 9 | validate output | `validate_output.py` | **re-import and verify** |
| 10 | render preview | `render_preview.py` → engine | preview image (never fatal) |

## 1. Validate the source

Nothing downstream runs until this passes:

- scheme/host allowed, not a private address (SSRF guard), redirects refused
- size within `MAX_AVATAR_BYTES`, streamed with a running cap
- GLB magic sniffed before parsing
- `sha256` matches, when the caller supplied one
- the file parses as glTF and carries a VRM extension
- **usage terms permit modification** (see [LICENSING.md](LICENSING.md))

## 2. Analyze the avatar

Rejects anything that is not a usable humanoid, then measures it:

```
height · shoulder width · chest · waist · hips
arm length · leg length · inseam · depth
```

Values measured directly between paired bones carry `confidence: 1.0`;
girth-like values are estimates and say so. Downstream stages and the fit
report both see the confidence.

## 3. Plan the outfit

Deterministic and reproducible — no model call is required:

```
"elegant dark red evening dress"
   category   = dress          (keyword)
   silhouette = sheath         ("column"/"fitted" family, or the template default)
   hem        = floor
   fabric     = —
   colour     = red, darkened by the "dark" modifier
   → template dress-evening-column-v1
```

`plan_with_llm` can fill gaps a vague prompt leaves, but never overrides what
the rules resolved, so a model outage degrades styling instead of breaking the
pipeline.

## 4. Generate the garment

The provider returns a `GarmentArtifact`. For the template path that is a
reference plus fitting parameters; for the AI path it is a downloadable mesh
flagged `requiresCleanup` / `requiresBlender`.

## 5–7. Fit, skin, resolve clipping

Shared by both engines (`engines/shell.py`):

1. build the garment shell at this avatar's measurements
2. sample the body and index it radially (height band × angular sector)
3. measure clearance, then **push any intersecting vertex outward** to
   `body radius + clearance`
4. re-measure and record the verdict

Then the engines diverge:

- **native** — bind to humanoid bones by distance-to-bone-segment, restricted to
  the template's anchor regions, with two corrections that matter:
  - influences far outside the nearest bone are dropped
  - a garment piece that is a *separate connected component* sitting on one side
    of the body cannot bind to the other side's bones. A pair of shoes is two
    shells and must not cross-bind; a skirt is one shell spanning both legs and
    *should* blend, because that is how fabric behaves.
- **blender** — shrinkwrap onto the real surface, transfer the body's own weights
  with a data-transfer modifier, limit to 4 influences, then mask covered body
  polygons. See [BLENDER_FITTING.md](BLENDER_FITTING.md).

### Pose tests

The bound garment is deformed with linear blend skinning through four poses —
`arms-down`, `walk`, `sit`, `legs-apart` — and checked for non-finite positions
and implausible edge stretch. Parent rotations propagate down the bone
hierarchy, so a boot attached below the knee follows the shin exactly rather
than reading as torn.

## 8. Assemble

New buffer views, accessors, material, mesh, and a skin whose joints are the
avatar's *own* humanoid nodes. Inverse bind matrices are the inverses of each
joint's world matrix, because the garment is authored in rest-pose world space
and its node stays at the scene root.

Also written: first-person mesh annotations, VRM 0.x `materialProperties`
alignment, a derived title, and provenance in `extras.wardrobeForge`.

## 9. Validate the output — the stage that counts

> "Blender returned exit code 0" is not a result.

The produced bytes are re-parsed from scratch and checked:

```
✓ file parses
✓ still carries a VRM extension
✓ humanoid mapping preserved, bone for bone
✓ head bone present (face tracking keeps working)
✓ expressions preserved
✓ skeleton preserved, no nodes lost
✓ a new garment mesh exists
✓ that mesh is skinned, with weights that normalise to 1.0
✓ no joint index outside its skin
✓ the original avatar is still recoverable
```

Any failure here fails the job. This is what `tests/e2e/test_acceptance.py`
asserts, across four body types and both VRM specs.

## 10. Render the preview

Never fatal: a look without a thumbnail is still a good look.

## Failure model

| Reason | State | Meaning |
| --- | --- | --- |
| `source_model_modification_not_permitted` | `rejected` | the model's own terms forbid it |
| `requires_user_license_attestation` | `rejected` | terms unknown; caller must assert |
| `source_is_not_a_vrm` | `rejected` | not a GLB, or no VRM extension |
| `source_is_not_humanoid` | `rejected` | required humanoid bones missing |
| `source_exceeds_size_limit` | `rejected` | over `MAX_AVATAR_BYTES` |
| `source_hash_mismatch` | `rejected` | sha256 did not match |
| `no_garment_template_matched` | `failed` | planner found nothing usable |
| `fitting_failed` | `failed` | geometry stage could not complete |
| `output_validation_failed` | `failed` | the result did not survive re-import |
| `garment_provider_error` | `failed` | the AI provider failed |

`rejected` means the caller can fix it. `failed` means we can.
