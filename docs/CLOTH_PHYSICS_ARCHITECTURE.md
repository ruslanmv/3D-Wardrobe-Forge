# Cloth physics architecture

Forge exports a versioned cloth asset. It does not simulate the garment, and it
does not invent a seated drape. The viewer in 3D-Avatar-Chatbot decides whether
to skin the mesh or to step an XPBD solver. The live Try-On pose corrector is
unchanged until a capture proves the solver.

Schema: `wardrobe.cloth/1`. Magic: `WCL1`. Implementation:
`wardrobe/cloth/asset.py`, `wardrobe/cloth/binary.py`, `wardrobe/cloth/topology.py`.

## What a garment is allowed to do

Category and kind choose the profile. The display name is used only when both
are empty, so a top whose name mentions a boot stays a top.

| Profile | Garments | Runtime |
|---|---|---|
| `skinning` | tops, underwear, swimwear | skeletal skinning |
| `corrective` | trousers, legwear, shorts, jumpsuits | skinning plus joint corrections |
| `rigid` | shoes | articulated, not cloth |
| `hybrid-skirt` | pencil silhouette | skinned waist, simulated hem |
| `cloth` | skirts, dresses, jackets, nightwear | XPBD when the boundary is sewn |

An open boundary that passes within 15 mm of another open boundary and does not
already share a welded vertex is a missing seam. It is counted. It is not
stitched. The asset then says `simulation: fallback-skinning` and
`reason: open boundary has no authored seam`. A degenerate triangle raises
`ClothAssetRejected` and the garment still exports, without a cloth asset.

## Attachment

Particle pin weights come from, in order:

1. `mesh.metadata["clothAttachment"]`, one weight per render vertex.
2. Triangles in a section whose name contains `waist`, or is `band` or `yoke`.
3. A height falloff (full over the top 4 cm, zero 8 cm down).

The third case sets `attachmentSource` to `height-fallback` and flag bit 0 in
the binary. That is a compatibility fallback, not an authored landmark.

## Binary layout

The glTF extra `wardrobeForge.clothAsset` holds counts, compliance, density,
damping, friction, the collision group, and LOD names. Particle arrays are one
little-endian buffer view, not a JSON string.

Header, 48 bytes: `WCL1`, version 1, flags, then counts for particles,
triangles, stretch, shear, bend, seams, attachments, render vertices, and LODs.

* positions `float32[particles * 3]`
* triangles `uint32[triangles * 3]`
* stretch and bend `(uint32 a, uint32 b, float32 rest)`
* shear `(uint32 baseA, uint32 baseB, uint32 opposite, float32 restAltitude)`
* seams `(uint32 renderA, uint32 renderB)` for coincident copies only
* attachments `(uint32 particle, float32 weight)` above zero
* bindings `(uint32 i0, i1, i2, float32 w0, w1, w2)` per render vertex

Each stored LOD then has a name, coarse positions, coarse triangles, and a map
from every full-resolution particle to one coarse particle. `mobile-low` is
always skinning and has no mesh. Budgets are starting points: mobile-mid 200,
mobile-high 500, desktop 1,200. A mesh already under the budget keeps `mesh:
full`. A hem, a slit, and a locked waistband vertex are not collapsed.

Stretch is one distance constraint per edge. Shear is the altitude onto the
longest edge of each triangle. Bend is the distance between the far corners of
two triangles that share an edge, the same isometric pair the static relaxer
uses.

## Geometry checks stay geometry checks

`extras.wardrobeForge.clothAsset` and the buffer view it names are metadata.
`tests/body_art_support.py` strips that payload before hashing a look, and
`tools/gallery/geometry_hashes.py` omits the key. Positions, indices, joints,
weights, images, and materials are still compared with the committed
baselines. Do not regenerate those baselines to absorb this metadata.

## What this repository does not do

Forge does not run the frame loop, replace `PoseClothCorrection.js`, or colour
the underskirt. The panty-coloured underskirt (4 cm past the outer hem, capped
at the ankle) is the open change on
[3D-Wardrobe-Forge pull request 26](https://github.com/ruslanmv/3D-Wardrobe-Forge/pull/26).
This branch does not edit that code.

Rollback: stop writing `clothAsset`. Older viewers ignore the extra. The mesh
bytes they already hashed are unchanged once the cloth view is stripped.
