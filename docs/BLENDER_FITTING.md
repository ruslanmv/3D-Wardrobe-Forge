# Blender fitting

The Blender worker is the critical component for *quality*. It is not required
for *correctness*: the native engine produces valid, wearable looks on its own.
Blender adds the three things a pure-Python engine cannot do.

| Capability | Why only Blender |
| --- | --- |
| Shrinkwrap onto the real surface | needs a mesh kernel and a BVH |
| Weight transfer from the body mesh | needs the body's own vertex groups |
| Body masking | needs polygon-level editing of the body |
| Generated-mesh cleanup | needs remeshing, decimation, welding |
| Rendered previews | needs a renderer |

## Requirements

- Blender 4.2+ headless
- [VRM Add-on for Blender](https://github.com/saturday06/VRM-Addon-for-Blender)

Both are baked into `Dockerfile.blender`. `BlenderEngine.available()` simply
checks whether `BLENDER_BIN` is on PATH, and `WARDROBE_ENGINE=auto` falls back
to native when it is not.

## Process boundary

Python never imports `bpy`, and the Blender modules never import `wardrobe`.
The only thing crossing the boundary is a JSON job spec:

```
wardrobe/engines/blender.py
      writes  workdir/job.json  +  workdir/garment.glb  +  workdir/source.vrm
      runs    blender --background --factory-startup --python-exit-code 1 \
                      --python worker/blender/run_pipeline.py -- --spec job.json
      reads   workdir/look.vrm  +  workdir/preview.webp  +  workdir/fit-report.json
```

The subprocess is bounded: a timeout, captured output, no shell, and the
process is killed on overrun. It is parsing an untrusted model.

The spec carries `humanoidBoneNames` as well as node indices, because Blender
identifies bones by **name** while glTF identifies them by index.

## Stages inside Blender

`worker/blender/run_pipeline.py` runs these in order:

| Module | Does |
| --- | --- |
| `import_vrm` | enable the add-on, import, find the armature and body (by skin weights, `body_select.py`: the largest mesh can be her hair) |
| `analyze_humanoid` | resolve humanoid bones: spec names → add-on mapping → name heuristics |
| `normalize_pose` | clear pose transforms so measurement and fitting see the rest pose |
| `measure_body` | measure from the *evaluated* scene (modifiers and shape keys included) |
| `import_garment` | import the measured shell, or the provider's generated mesh |
| `fit_generated_mesh` | weld, drop loose parts, recalc normals, triangulate, decimate, align |
| `fit_template` | shrinkwrap at the template's clearance, then smooth |
| `transfer_weights` | data-transfer the body's vertex groups, limit to 4 influences, bind |
| `resolve_clipping` | BVH nearest-surface test, push intersecting vertices out |
| `generate_body_mask` | collect covered body vertices, feather the border, Mask modifier |
| `setup_materials` | MToon when the add-on offers it, otherwise Principled BSDF |
| `validate_scene` | structural checks and pose tests, *before* exporting |
| `export_vrm` | VRM export via the add-on |
| `render_turntable` | EEVEE front view |

## Why the shell is imported rather than rebuilt

The orchestrator builds the measured garment shell in Python and hands Blender
a GLB. That keeps garment shape identical across both engines — only fitting
accuracy differs — and means there is exactly one place where garment geometry
is defined.

## Body masking

The body is **never destroyed**. Covered vertices go into a vertex group named
`WardrobeForgeBodyMask`, which a Mask modifier hides. The original geometry
stays in the file and the effect is reversible.

One ring of vertices around the hole is deliberately kept (`_feather_border`),
so no gap opens at a hem where the garment and body meet.

## Pose tests

`validate_scene.run_pose_tests` poses the real armature through `arms-down`,
`walk`, `sit` and `legs-apart`, and measures the garment's evaluated bounding
box against its rest bounds. Growth beyond 2x means the weighting is wrong, not
that the pose is extreme. Poses are reset between tests.

## Debugging a run

```bash
export BLENDER_BIN=/opt/blender/blender
export DELETE_SOURCE_AFTER_JOB=false        # keep the job workdir
wardrobe-forge create --avatar mira.vrm --prompt "a red dress" --engine blender
```

The workdir path is logged. It contains `job.json`, `garment.glb`,
`source.vrm`, and whatever Blender managed to write. To re-run just the Blender
half:

```bash
/opt/blender/blender --background --factory-startup --python-exit-code 1 \
  --python worker/blender/run_pipeline.py -- --spec /tmp/wardrobe-job_.../job.json
```

Blender's full stdout is captured; the last 4000 characters are attached to the
job error when it exits non-zero.

## Blender API drift

Blender's Python API changes between releases and the VRM add-on's operator
signatures change with it. The code tolerates this deliberately:

- `export_vrm` inspects the operator's RNA and passes only the properties this
  build accepts
- `analyze_humanoid` tries the add-on's VRM 1.0 layout, then its 0.x layout,
  then bone-name heuristics
- `setup_materials` falls back from MToon to Principled BSDF
- `render_turntable` picks `BLENDER_EEVEE_NEXT` or `BLENDER_EEVEE` by probing

The `blender-integration` workflow pins exact versions and runs nightly, so
drift is caught there rather than in production.
