# Body fix playbook: Rinna, VRoid Female, VRoid Male, AvatarSample_O

How an artist fixes the four library characters whose body blocks the bare state, with the tools
the industry already uses, and only the checks this repository already has. Nothing here adds a
gate. Per-character numbers (bones, expressions, face and hair primitives) are in
`docs/qa/body-state-specs/<slug>.md`.

| Character | Problem (CV1, measured) | Fix |
|---|---|---|
| Rinna | clothing painted on the skin texture, no garment meshes | Route A or B |
| VRoid Female | default underwear painted on | Route A or B |
| VRoid Male | default briefs painted on | Route A or B |
| AvatarSample_O | chest deleted from the mesh under the dress | Route C, then A |

## Route 0 first: build the file automatically (CG5, minutes, no artist)

Forge already does Route A's skin painting (`skin_restore`, the readiness report's
`restoration-completed`) and Route C's chest fill (BR1's BC1 patch) inside every bare look.
`build_body_state.py` writes that result to a file and pre-flights it:

```bash
python tools/fetch_library.py          # the two VRoid bodies are not in git
python tools/body_surface/build_body_state.py --all --out <private dir> --json <private dir>/report.json
```

Measured 2026-11-17 on the four exact library files, about 20 s in all: every output passes all
nine structural checks (closed in all six bands, no clothing left, rig, expressions, face and
hair, metadata kept), and the build is byte-for-byte deterministic. O's file says it is
reconstructed (`reconstruction: bc1-proxy`, regions `upper`) so a reviewer can tell.

What remains is only what was always a person's job, and nothing here automates it:

1. A `clearly-adult` review of each source file and of each output's exact bytes (Studio ▸
   Character review), by an independent reviewer.
2. The operator's licence and rights statement, and `WARDROBE_ADULT_BODY_SURFACE` on the server.
3. Import in the Studio, then `gates.py audit` and the app checks (Phase 4 below).

Use Routes A to C only if the reviewer finds the automatic skin or patch not good enough (O's
patch is featureless by construction), or for Route B's real garments long term.

## The rule every route follows

Change the body, never the identity. A delivered file keeps the same skeleton (bone names, rest
positions within 1 mm), every expression by name, face and hair vertex for vertex (0.1 mm), and
the same VRM title and authors. That is what lets every animation, pose and look made for her
still fit. `body_state_import.check` verifies all of it automatically on import.

## Tools

- **VRoid Studio** (free): best when a `.vroid` project exists for the character.
- **Blender 4.x + VRM Add-on for Blender** (free, `saturday06/VRM-Addon-for-Blender`): import,
  edit, export VRM 0.x and 1.0 without losing humanoid mapping, expressions or spring bones.
- **Krita, Substance Painter or Blender texture paint**: texture work on the body UV.

## Route A: a bare body-state file (painted-on clothing)

Industry name: a *base-body variant*. Same character, clothing layer removed.

1. Import the exact library file into Blender with the VRM add-on. Confirm its SHA-256 matches
   the spec sheet first: a body state is bound to that file.
2. Delete every garment mesh or primitive (Rinna and the VRoid bodies have none).
3. Open the body skin texture (the `_SKIN` material). On a new paint layer, paint skin over the
   painted clothing. Sample colours from the arms and stomach, follow the existing shading, and
   keep it featureless where clothing was. Extend 2 to 3 px past the clothing edge so no outline
   remains, and fill the UV island padding too (texture filtering samples it).
4. Where the texture's alpha cut skin away (VRoid hides skin under clothes this way), set alpha
   to opaque in that region. If the shade texture (MToon) or the normal map carries the
   clothing's folds, clean those maps in the same region.
5. Do not touch the face, hair, eyes, hands or feet materials, or any geometry.
6. Export as VRM in the same version as the source, with the same meta (title, authors).

If the `.vroid` project is available, the fastest equivalent: in VRoid Studio, remove the
clothing items, set underwear to none, export. Then check identity, since a VRoid re-export can
renumber vertices; if it does, use the Blender route instead.

## Route B: real garments (preferred long term)

Industry name: *layered clothing*. This is how VRChat, Roblox layered clothing and most avatar
platforms work: a complete body, clothes as separate meshes on top.

1. Do Route A's texture work so the body under the clothes is skin.
2. Model each garment as its own mesh over the body (or, from a `.vroid` project, export with
   clothing as separate meshes rather than baked into the skin).
3. Skin each garment to the same armature (Blender: Data Transfer modifier, vertex weights from
   the body, nearest face interpolated), then hand-fix shoulders, hips and knees.
4. Export. The result is a new clothed source file: Forge's clothing visibility (CV1) and its own
   bare body state then work on it with no body-state import at all. It has a new SHA-256, so it
   goes into the library pinned under that hash.

## Route C: rebuild a missing chest (AvatarSample_O)

1. Import the exact file into Blender. Hide the dress, top and shoes primitives to see the hole:
   no skin surface from about 0.96 m to 1.13 m up her body.
2. Rebuild the torso surface in that band as part of `Body (merged)`. Practical method: bridge
   the open edge loops above and below, then shape to her silhouette, or retopologise from a
   reference torso of matching proportions you have the rights to. Keep the topology even and
   the edge loops continuous with the existing ones.
3. Weights: Data Transfer from the surrounding body (vertex groups, nearest face interpolated),
   then smooth across `J_Bip_C_Spine`, `J_Bip_C_Chest`, `J_Bip_C_UpperChest` and the shoulders.
   Test by posing arms up and forward: no tearing at the seam.
4. UVs: unwrap the new faces into free space on the existing body texture, then paint them to
   match (Route A, step 3). Make the alpha-cut band around the hole opaque.
5. Change nothing else. Export: this is a completed source file (new SHA-256, pinned in the
   library). Then make its body state with Route A.

## Check before sending (existing tools only)

```bash
python tools/body_surface/asset_spec.py --preflight --slug <slug> --candidate <file.vrm> \
    --state bare --sha256 <sha256 of file.vrm>
```

It prints every check `body_state_import.check` will run: structure, rig, expressions, face and
hair, closed body bands, no clothing left. Fix anything it lists, then deliver.

## Deliver

- the `.vrm` and its SHA-256;
- a short statement that the artist holds the rights to the work, and the licence it is
  delivered under (it must be compatible with how this repository and the app are licensed);
- which route was used, and for Route C the source file it was made from.

Import in the Studio (admin session, Settings, body states, Import). The import runs the same
checks as the preflight and, like every bare file, needs a recorded `clearly-adult` review of
the delivered file's exact bytes (the existing rule; nothing new).
