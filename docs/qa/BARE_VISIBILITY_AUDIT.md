# AF4 — Bare-body visibility audit

2026-11-15, `feat/bare-base-body`. The full path, source → garment inventory → preservation → skin
restoration → body validation → export, run with `prepare()` on each of the eight library sources
(`python tools/audit/bare_visibility.py` → `work/af4-bare-audit.json`; reads only).

## Results per character

| Character | Bare | Removed | Accessors verified unchanged | Expression binds lost | Morph counts changed | Alpha modes changed | Materials changed |
|---|---|---|---|---|---|---|---|
| AvatarSample A | refused — body not closed | — | — | — | — | — | — |
| AvatarSample B | refused — body not closed | — | — | — | — | — | — |
| AvatarSample C | built | tops, bottoms, shoes | 255 | 0 | 0 | 0 | skin texture only (painted clothing restored) |
| VRoid Female | built | — (clothing is painted) | 133 | 0 | 0 | 0 | skin texture only |
| VRoid Male | built | — (clothing is painted) | 133 | 0 | 0 | 0 | skin texture only |
| AvatarSample O | refused — body not closed (deleted under clothes) | — | — | — | — | — | — |
| Model Girl | built | tops, bottoms, onepiece, shoes | 140 | 0 | 0 | 0 | none |
| Rinna | built | — (clothing is painted) | 126 | 0 | 0 | 0 | skin texture only |

"Accessors verified unchanged" covers every retained POSITION, NORMAL, TEXCOORD, JOINTS, WEIGHTS,
index and morph-target accessor (byte-identical). Normal maps are kept. No mesh is renumbered
(`remove_garments` drops primitives inside a mesh or detaches a whole-mesh garment from its node),
so VRM expression binds keep pointing at the meshes they drive.

## Skin restoration

Of the texels the restorer changed, 0.3–0.4 % were skin-coloured beforehand (VRoid Female 0.4 %,
Rinna 0.3 %, AvatarSample C 0.4 %): it repaints painted clothing, not her authored pigmentation.
Its fill is an interpolation of the surrounding skin by construction — it never invents detail.

## Defects found and repaired

1. **Anatomy-labelled material detected as clothing caused a refusal.** A primitive whose own
   material the author labels anatomical (by name, or `extras.authoredAnatomy`) is now kept on her
   body — not stripped, not a refusal — with byte-identical geometry, and listed in the report's
   `keptAnatomicalMaterials` so a mislabelled garment is visible in review. A whole node or mesh
   labelled anatomical that also holds detected garments still refuses (ambiguous at the primitive
   level). Test: `test_anatomy_labelled_material_detected_as_clothing_is_kept` (fails on the old code
   with `BodyIncompleteForBare`, passes now).
2. **Painted footwear stayed on the bare body.** `restore_skin` restores from the ankles up; Rinna's
   feet are 94 % painted black (socks), AvatarSample C's 13 %. The bare path now passes
   `include_feet=True`; every other mode is unchanged (the default stops at the ankles). After: 0 %
   dark paint in every band (feet, shins, thighs, pelvis, torso) on Rinna, C and VRoid Female. Test:
   `test_bare_is_barefoot_and_other_modes_still_stop_at_the_ankles`.

## Checked and found correct

- No censor mesh, blur, mosaic, pixelation or modesty material exists in Forge or the companion app.
- Opaque-clothing body masking (`body_surface/masking.py`) belongs to the Blender engine; the bare
  path is native and never masks. A source whose stored look had body polygons masked away fails the
  body check and is refused, never patched.
- Alpha: cut-away skin under painted clothing is made solid only where the restorer fills it; no
  material's `alphaMode` changes.
- `body-bare-v1` stays authored-only: BC1 completion is never called, bodyProxy inputs are refused,
  no garment is generated, output is private and tagged `bare: true`, prebuilding stays manual and
  keep-existing, cache keys and the pipeline version are unchanged.

## Not covered here

Visual QA renders (front/back/side/three-quarter) of the bare outputs were not regenerated in this
pass; the matrix above is measured on the documents. The sources contain no genital or nipple
anatomy (`ANATOMY_SOURCE_INVENTORY.md`), so a faithful bare body of these characters is a smooth body.
