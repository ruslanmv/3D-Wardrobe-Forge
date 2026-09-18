# Architecture

## The contract

```
Input:  a compatible VRM avatar + an outfit request
Output: the same character wearing a new outfit as a validated VRM,
        plus a preview image and wardrobe metadata
```

Everything else is an implementation detail. In particular, **the chatbot must
never learn about Blender, Meshy, Tripo, fitting, skin weights or clipping.**
It asks for a look and receives a `.vrm` it already knows how to load.

## Component map

```
                        3D WARDROBE FORGE

  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
  │  FastAPI     │ enqueue│   Job queue  │  pull  │   Worker     │
  │  apps/api    ├───────►│ asyncio/redis├───────►│ orchestrator │
  └──────┬───────┘        └──────────────┘        └──────┬───────┘
         │                                               │
         │ reads                                         │ runs stages
         ▼                                               ▼
  ┌──────────────┐                            ┌────────────────────┐
  │ repositories │                            │ wardrobe/pipeline  │
  │ jobs +       │◄───────────────────────────┤ 10 ordered stages  │
  │ wardrobes    │              writes        └─────────┬──────────┘
  └──────────────┘                                      │
                                                        │ delegates geometry
  ┌──────────────┐                            ┌─────────▼──────────┐
  │ object store │◄───────────────────────────┤  wardrobe/engines  │
  │ local or S3  │        artifacts           │  native | blender  │
  └──────────────┘                            └─────────┬──────────┘
                                                        │
                                   ┌────────────────────┴───────────┐
                                   ▼                                ▼
                        ┌────────────────────┐        ┌────────────────────┐
                        │   wardrobe/vrm     │        │  worker/blender    │
                        │ pure-Python glTF   │        │  bpy, VRM add-on   │
                        └────────────────────┘        └────────────────────┘
```

## The layer that matters: `wardrobe/vrm`

A VRM file is a GLB container. That means a large amount of genuinely useful
work needs no 3D application at all:

| Module | Responsibility |
| --- | --- |
| `glb.py` | strict GLB container read/write |
| `document.py` | mutable glTF document: accessors, nodes, world matrices |
| `inspect.py` | VRM 0.x / 1.0 detection, humanoid bones, normalised licence terms |
| `measure.py` | body measurement from the rest pose |
| `skinning.py` | automatic skin binding to humanoid bones |
| `merge.py` | inject a skinned garment into an existing VRM |
| `export.py` | write a standalone mesh as GLB |
| `build.py` | generate synthetic humanoid VRM fixtures |

Because this layer exists, validation, analysis, assembly and re-import
verification all run in CI on every commit, with no Blender and no third-party
avatar binaries.

## Two engines, one interface

Both implement `wardrobe/engines/base.py:FittingEngine`, and both start from
the *same* measured garment shell (`engines/shell.py`), so garment shape is
identical across engines and only fitting quality differs.

| | `native` | `blender` |
| --- | --- | --- |
| Requirements | Python only | Blender + VRM add-on |
| Garment shape | parametric shell built at the avatar's measurements | same shell, then shrinkwrapped to the real surface |
| Skin weights | analytic binding to humanoid bones | data-transfer from the body mesh |
| Clipping | radial push-out, guaranteed outside the body | BVH intersection test and repair |
| Body masking | ✗ reports coverage only | ✓ hides covered polygons |
| Generated (AI) meshes | ✗ | ✓ cleanup, retopology, alignment |
| Preview | software rasteriser | EEVEE render |
| Runs in CI | every commit | nightly / on Blender changes |

`WARDROBE_ENGINE=auto` picks Blender when its binary is present and falls back
to native otherwise. A deployment with no Blender still produces real,
wearable looks — it just cannot hide the body underneath a tight garment.

## Why the shell is built rather than deformed

The obvious design is to author a dress mesh and deform it onto each body. That
fails in the way that matters: fitting an arbitrary donor mesh onto an unknown
body is where shrinkwrap artefacts, inverted normals and broken weights come
from, and it fails differently on every avatar.

Instead the template declares *parameters* and the shell is generated at the
avatar's own measurements. Fitting therefore cannot fail the way a shrinkwrap
can. The acceptance matrix (4 bodies x 2 VRM specs x 7 garments) passes
deterministically because of this choice.

Blender then adds accuracy on top of a shape that is already correct.

## Stage boundaries

Stages are pure-ish functions over a `PipelineContext`; the orchestrator owns
ordering, state transitions, persistence and failure mapping. Every failure
carries a stable `FailureReason` code, so the client can branch on
`requires_user_license_attestation` without parsing prose.

## Extension points

| Want to change | Touch only |
| --- | --- |
| Add a garment | a JSON file in `assets/garment_templates/` |
| Add a garment shape | `wardrobe/geometry/procedural.py` |
| Add an AI mesh provider | `wardrobe/providers/`, implementing `GarmentProvider` |
| Swap storage | `wardrobe/storage/object_store.py` |
| Swap the queue | `wardrobe/queue/jobs.py` |
| LLM-assisted styling | `plan_with_llm` in `wardrobe/pipeline/plan_outfit.py` |

## Stack

| Layer | Choice | Note |
| --- | --- | --- |
| API | FastAPI | plus SSE for progress |
| Models | Pydantic v2 | camelCase aliases on the wire |
| Queue | asyncio (default), Redis | `WARDROBE_JOB_BACKEND` |
| State | in-memory or JSON-on-disk | PostgreSQL slots behind the same repository interface |
| Storage | local FS or S3-compatible | signed URLs on S3 |
| 3D | pure-Python glTF, optional Blender | |
| Client | JavaScript ESM | `clients/javascript/` |
