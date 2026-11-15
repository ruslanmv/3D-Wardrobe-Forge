# Bare authored-body mode — development review

Base: `ultimate` at `8512004`. Branch: `feat/bare-base-body`.

## Contract

`body-bare-v1` is a restricted, colourless catalogue entry, not a garment builder. Request it with
`options.baseBody: "bare"` through the authenticated private library-job route. The existing adult
body-surface gate is authoritative: model terms, operator switch, then the model's adult declaration.
No new declaration or model permission is inferred. Public generation routes refuse this mode.
Private markers precede output publication; output metadata has `extras.wardrobeForge.bare: true`.

The native document path strips every detected garment with the existing strip planner. It restores
painted skin between ankles and neck and samples authored torso, pelvis, and separate thigh/shin bands.
Unknown bone spans fail closed. An incomplete band returns `body-incomplete-for-bare`; BC1 completion
is never called. Inputs already containing a bodyProxy are refused. No garment provider runs.
Hair, face, eyes and accessories not identified as clothing remain attached.

Bare is not an anatomy generator. It preserves the avatar's authored geometry; it does not add genital
anatomy absent from a source, import meshes, or use MakeHuman/SMPL-family reference bodies. A completed
bare job means garment removal and the implemented surface checks passed, **not** that a detailed
anatomical source asset has been demonstrated. That additional realism requirement remains subject
to source inspection and access-controlled visual review.

## Anatomical fidelity

Bare preparation fingerprints retained POSITION, NORMAL, UV, skin-weight/joint, index and morph-target
accessors and verifies that their data did not change. Existing body normal maps are preserved rather
than flattened by the shared texture restorer. Author-labelled anatomical materials are protected
from repainting; if clothing still shows, painted-skin QA refuses rather than blanking those materials.

Painted-clothing detection is a colour-based heuristic, not a semantic anatomy classifier. Unlabelled
anatomical pigmentation cannot be certified by this heuristic alone. Review actual source/output
textures and meshes before claiming anatomical fidelity. No generic body or concealment geometry is
substituted. Existing clothing modes retain their prior restoration behaviour.

Only `clients/javascript/WardrobeController.js` exists here among the named NEXUS wardrobe controllers.
It was inspected and left unchanged. TryOnSession, TryOnUnderneath, InSceneWardrobe and
OutfitDecisionEngine are not in this repository. This branch does not claim a verified NEXUS Private
pose/undress/redress sequence in the companion application's separate runtime.

## Additive storage and prebuild

The pipeline version and existing key serialization are unchanged. No template-model fields were
added. Existing templates, cache-key baseline, gallery artifacts and reference bodies remain intact.
Bare jobs bypass cached responses so the current gate always executes. Bare cache/index writes keep
existing entries. Normal prebuild invocations exclude the new template; it is manual only:

```sh
python tools/prebuild.py --forge http://127.0.0.1:8090 \
  --admin-token-file /path/to/local-admin-token --only body-bare-v1 --workers 1 \
  --report work/bare-prebuild-report.json
```

The server must explicitly enable `WARDROBE_ADULT_BODY_SURFACE`. This is not a deployment instruction.
The tool requests no colour or foundation, checks the private prebuilt list first, skips existing bare
looks without submitting another job, and includes machine-readable refusal codes in the report.
No scheduled prebuild, existing palette, or gallery file is changed.

## Reproduce private evidence

```sh
python tools/audit/bare_body.py --out work/bare-review \
  --adult-body-surface --include-lingerie
node tools/gallery/views.mjs work/bare-review
```

The output directory must not exist; it is created private to its owner. The audit reads the library's
actual adult declarations and permissions, records every outcome and generates a front/back/side/
three-quarter manifest. Refused sources have no bare VRM and no fabricated bare image. Renders use the
Studio viewer without form/ghost substitutions. Keep the VRMs and images access-controlled rather than
committing adult look outputs to a public repository. Rendering dependencies are those of the existing
`tools/gallery` renderer. A CDN access failure must be reported, not treated as successful rendering.

## Development build matrix

Local gate enabled explicitly; library declarations and model terms preserved:

| Character | Bare build | Reason |
|---|---|---|
| AvatarSample A | Refused | body-incomplete-for-bare |
| AvatarSample B | Refused | body-incomplete-for-bare |
| AvatarSample C | Built | Authored-body band checks passed |
| VRoid Female | Built | Authored-body band checks passed |
| VRoid Male | Built | Authored-body band checks passed |
| AvatarSample O | Refused | body-incomplete-for-bare |
| Model Girl | Built | Authored-body band checks passed |
| Rinna | Built | Authored-body band checks passed |

All eight lingerie comparison jobs completed in the separate audit store. No refusal was bypassed.
Surface-band closure is a sampled smoke check, not a mathematical watertightness proof. Anatomical
realism is not declared READY merely because a row says Built.

## Validation

Relevant automated checks cover gate refusals and order, conflicting parameters, AvatarSample O's
refusal without BC1, absence of garment generation, output tagging, painted-skin removal, unchanged
authored positions, colourless restricted catalogue metadata and manual/keep-existing prebuilding.
The existing cache-key stability fixture is unchanged and its tests pass. Hash verification found no
changes in 265 pre-existing gallery/reference/fixture files.

A broad unit run was interrupted after 53 passing test cases in a costly unrelated anatomy-reference
calculation; it was not reported as a complete suite pass. Targeted and relevant regression results
are recorded separately in the private development audit logs. The relevant regression run passed
64 cases; the focused bare/prebuild/cache-key run passed 15 cases and is recorded in `final-tests.log`. No PR, merge or deployment performed.
