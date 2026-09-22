# VRM compatibility

## What "any VRM" means here

> Any valid VRM 0.x or 1.0 humanoid whose geometry can be analysed and whose
> usage terms allow modification.

Anything else **fails cleanly** with a stable reason code rather than producing
a corrupt avatar. That distinction is the whole point of stage 1.

## Accepted

| | Support |
| --- | --- |
| VRM 1.0 (`VRMC_vrm`) | ✓ |
| VRM 0.x (`VRM`) | ✓ |
| GLB container, self-contained | ✓ |
| Base64 `data:` buffers | ✓ inlined on load |
| Interleaved vertex attributes | ✓ |
| Node hierarchies with `matrix` or TRS | ✓ |
| MToon materials on the source | ✓ preserved untouched |
| Blend-shape / expression sets | ✓ preserved, and verified after export |
| Spring bones | ✓ preserved (the garment does not get them; see limitations) |

## Rejected, on purpose

| Case | Reason code |
| --- | --- |
| Not a GLB container | `source_is_not_a_vrm` |
| GLB with no VRM extension | `source_is_not_a_vrm` |
| External buffer/image files (`buffer.uri` pointing at a file) | `source_uses_unsupported_features` |
| Sparse accessors | `source_uses_unsupported_features` |
| Missing required humanoid bones | `source_is_not_humanoid` |
| Humanoid bone pointing at a nonexistent node | `source_is_not_humanoid` |
| No mesh nodes, or no skins | `source_is_not_humanoid` |
| Degenerate rig (no hips, zero height) | `source_is_not_humanoid` |
| Over `MAX_AVATAR_BYTES` | `source_exceeds_size_limit` |
| Terms prohibit modification | `source_model_modification_not_permitted` |
| Terms unknown, no attestation | `requires_user_license_attestation` |

## Required humanoid bones

The VRM 1.0 required set, which is also what the fitting stage needs:

```
hips  spine  head
leftUpperArm  leftLowerArm  leftHand
rightUpperArm rightLowerArm rightHand
leftUpperLeg  leftLowerLeg  leftFoot
rightUpperLeg rightLowerLeg rightFoot
```

Improve fit quality when present, never fatal when absent:
`chest`, `upperChest`, `neck`, `leftToes`, `rightToes`.

## Output version

`options.outputVersion` accepts `source` (default), `VRM0` or `VRM1`.

The native engine currently always writes **the same spec it read** — it edits
the existing document rather than rebuilding it, which is precisely why the
humanoid, expressions and materials survive untouched. Cross-version conversion
is the Blender exporter's job; ask for it explicitly and use the Blender engine.

## Licence field mapping

Normalised across both specs so nothing downstream branches on version:

### VRM 1.0

`meta.modification` maps directly:

| VRM value | Normalised |
| --- | --- |
| `allowModificationRedistribution` | `allowed_with_redistribution` |
| `allowModification` | `allowed` |
| `prohibited` | `prohibited` |
| anything else / absent | `unknown` |

### VRM 0.x

VRM 0.x has no modification field; the licence name carries it:

| `meta.licenseName` | Normalised | Why |
| --- | --- | --- |
| `CC0`, `CC_BY`, `CC_BY_NC`, `CC_BY_SA`, `CC_BY_NC_SA` | `allowed` | derivatives permitted |
| `CC_BY_ND`, `CC_BY_NC_ND` | `prohibited` | **ND = NoDerivatives** |
| `Redistribution_Prohibited` | `allowed` (redistribution `false`) | VRoid's default: derive for yourself, do not share |
| `Other`, absent | `unknown` | check `otherLicenseUrl` |

## Known limitations

- **Spring bones on the garment.** The source's spring bones are preserved, but
  a generated garment is not given any, so a long skirt does not yet swish. It
  deforms correctly with the skeleton; it just has no secondary motion.
- **Body masking needs Blender.** The native engine guarantees the garment sits
  outside the body but cannot delete the polygons underneath it.
- **Textures are solid colours.** Material parameters (base colour, roughness,
  metallic) are planned from the prompt; pattern textures are not generated yet.
- **Garment sections are not stitched.** A procedural garment is composed of
  separate lofted sections (bodice, skirt, sleeves, trouser legs) rather than
  one watertight surface, so a small seam can be visible where sections meet.
  They are correctly positioned and weighted; they are simply not welded.
- **Measurement confidence.** Widths between paired bones are exact; chest and
  waist are estimated and reported with a confidence below 1.0.

## Testing against real avatars

The suite runs on generated fixtures (`wardrobe/vrm/build.py`) with four
distinct body types, so CI needs no third-party binaries. To check a real file:

```bash
wardrobe-forge inspect --avatar path/to/avatar.vrm
```

It prints the detected spec, the humanoid map, measurements and any issues, and
exits non-zero when the model would be rejected.
