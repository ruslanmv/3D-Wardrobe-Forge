# 3D-Wardrobe-Forge

Outfit generation for VRM avatars.

By default the CLI now packages generated looks as a static `yourfriend.online` wardrobe bundle. The same pipeline can also run as a hosted FastAPI service (including a Hugging Face Docker Space).

> **Input:** a compatible VRM avatar + an outfit request
> **Output:** the same character wearing a new outfit as a validated VRM, plus
> a preview and wardrobe metadata.

That is the entire contract. The calling application never learns about
Blender, Meshy, Tripo, fitting, skin weights or clipping — it asks for a look
and receives a `.vrm` it already knows how to load.

```
             ┌─────────────────────────┐
             │    source-avatar.vrm    │
             └────────────┬────────────┘
                          ▼
                 Analyze humanoid
                 body + skeleton
                          │
User prompt ─────► Outfit Planner
"elegant dark red         ├──────── Template path (production)
 evening dress"           └──────── AI-generated path (experimental)
                          ▼
                    Garment mesh
                          ▼
                 Automatic fitting
                    ┌─────┴─────┐
                 Skinning    Body mask
                    └─────┬─────┘
                          ▼
                    VRM assembly
                          ▼
                     Validation
             ┌─────────────────────────┐
             │ avatar-new-look.vrm     │
             │ preview.webp            │
             │ wardrobe.json           │
             │ fit-report.json         │
             └─────────────────────────┘
```

## Quick start

```bash
pip install -e ".[dev,preview]"

# Generate four calibration avatars to play with
wardrobe-forge fixtures --out assets/fixtures

wardrobe-forge create \
  --avatar assets/fixtures/calibration-b-medium-vrm1.vrm \
  --prompt "elegant dark red evening dress"
```

```
job job_…: completed
  plan: Red Evening  [dress/sheath/floor]  template=dress-evening-column-v1
  fit report (engine=native):
    PASS  vrm valid
    PASS  humanoid valid
    PASS  weights valid
    PASS  skeleton preserved
    PASS  expressions preserved
    PASS  source recoverable
    PASS  preview rendered
    ----  clipping: passed

dist/yourfriend-online/
├── wardrobe.json
├── avatars.json
├── catalog.json
├── provenance.json
└── looks/
    └── calibration-b-medium-vrm1/
        └── look-…/
            ├── look.vrm
            ├── preview.webp
            ├── look.json
            └── fit-report.json
```

That runs with **no Blender, no API keys and no third-party assets**.

The legacy flat output remains available with `--target generic`. See [docs/YOURFRIEND_ASSET_BUNDLE.md](docs/YOURFRIEND_ASSET_BUNDLE.md).

## As a service

```bash
cp .env.example .env
docker compose up --build
```

```bash
# Upload once, then generate as many looks as you like
KEY=$(curl -s -F file=@mira.vrm http://localhost:8080/v1/avatars | jq -r .storageKey)

curl -s -X POST http://localhost:8080/v1/jobs \
  -H 'content-type: application/json' \
  -d "{\"avatar\":{\"storageKey\":\"$KEY\",\"avatarId\":\"mira\"},
       \"outfit\":{\"prompt\":\"black satin cocktail dress\"}}"
```

For product integrations you can also submit the smaller `POST /v1/generate` facade, which delegates to the same job pipeline. Then poll `GET /v1/jobs/{id}` or subscribe to `GET /v1/jobs/{id}/events`.
Full reference: [docs/API.md](docs/API.md).

## How it actually works

A VRM is a GLB container, so most of the job needs no 3D application:
`wardrobe/vrm/` parses, validates, measures, skins and reassembles VRM files in
pure Python. That is why the entire acceptance suite runs in CI on every commit.

Garments are **generated at each avatar's own measurements** rather than
deformed onto them. A template declares parameters — coverage, anchors,
clearance, silhouette, hem — and the shell is built to fit. Fitting therefore
cannot fail the way a shrinkwrap can.

Two engines implement the same interface and share the same shell:

| | `native` | `blender` |
| --- | --- | --- |
| Needs | Python only | Blender + VRM add-on |
| Skin weights | analytic binding to humanoid bones | transferred from the body mesh |
| Clipping | radial push-out, guaranteed outside the body | BVH test and repair |
| Body masking | ✗ (reports coverage) | ✓ hides covered polygons |
| AI-generated meshes | ✗ | ✓ cleanup and retopology |
| Preview | software rasteriser | EEVEE render |

`WARDROBE_ENGINE=auto` uses Blender when it is installed and native otherwise.

## The bar for "it works"

Not "the exporter exited 0". The produced bytes are re-imported from scratch and
checked:

```
✓ file parses                    ✓ garment has valid weights
✓ humanoid mapping preserved     ✓ animation poses work
✓ head/face still work           ✓ severe body intersections absent
✓ skeleton preserved             ✓ original avatar remains recoverable
✓ expressions preserved          ✓ preview renders
```

`tests/e2e/test_acceptance.py` asserts all of it across **7 garments × 4 body
types × 2 VRM specs**. The four calibration bodies span 1.48 m to 1.83 m with
hip widths varying by more than 1.5×, and a test enforces that they stay
different.

## Try-On Haul, on the client

```js
const forge = new WardrobeClient({ baseUrl: WARDROBE_FORGE_URL });
const wardrobe = new WardrobeController({ forge, viewer: window.NEXUS_VIEWER });

await wardrobe.tryOnHaul([
    'elegant burgundy evening dress',
    'cozy oversized wool coat',
    'slim blue denim jeans',
], { holdMs: 5000 });
// returns to the original avatar at the end
```

`clients/javascript/` drives `3D-Avatar-Chatbot`'s existing `AvatarManager`
through its public API — the viewer needs no changes. See
[docs/3D_AVATAR_CHATBOT_INTEGRATION.md](docs/3D_AVATAR_CHATBOT_INTEGRATION.md).

## Licensing is a pipeline stage

A VRM carries usage terms, and deriving a new model is exactly what they
govern. The check runs **before** any geometry work:

- terms prohibit modification → `451`, `source_model_modification_not_permitted`
- terms unknown → `428`, `requires_user_license_attestation`
- the caller's attestation can *supply* missing terms, never override a
  prohibition

VRoid Hub conditions-of-use objects are accepted verbatim, in the shape the
chatbot's VRM Manager already stores. See [docs/LICENSING.md](docs/LICENSING.md).

## Garment library

17 templates across dresses, tops, skirts, trousers, jackets and shoes. Adding
a garment is usually a single JSON file — see
[docs/GARMENT_TEMPLATE_SPEC.md](docs/GARMENT_TEMPLATE_SPEC.md).

```bash
wardrobe-forge templates          # list and validate the library
wardrobe-forge inspect --avatar mira.vrm
```

## Development

```bash
make install        # editable install with dev extras
make test           # the whole suite
make test-e2e       # the acceptance matrix
make test-blender   # skipped unless Blender is installed
make lint
make dev            # API with reload on :8080
```

## Status

M0–M4, M6 and M7 are done; M5 (AI-generated meshes) has adapters and Blender-side
cleanup written but is unverified against the live provider APIs. The current
state of every milestone, the design decisions behind it, and the bugs the
acceptance matrix caught are in
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Documentation

| | |
| --- | --- |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | components, layers, extension points |
| [PIPELINE](docs/PIPELINE.md) | the ten stages and the failure model |
| [API](docs/API.md) | HTTP reference |
| [GARMENT_TEMPLATE_SPEC](docs/GARMENT_TEMPLATE_SPEC.md) | template schema, `coverage` vs `anchors` |
| [WARDROBE_SPEC](docs/WARDROBE_SPEC.md) | manifest format |
| [BLENDER_FITTING](docs/BLENDER_FITTING.md) | the Blender worker |
| [VRM_COMPATIBILITY](docs/VRM_COMPATIBILITY.md) | what is accepted, what is rejected, limitations |
| [SECURITY](docs/SECURITY.md) | threat model and privacy |
| [LICENSING](docs/LICENSING.md) | usage terms as a pipeline stage |
| [3D_AVATAR_CHATBOT_INTEGRATION](docs/3D_AVATAR_CHATBOT_INTEGRATION.md) | client integration |
| [IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md) | milestones and next steps |
| [YOURFRIEND_ASSET_BUNDLE](docs/YOURFRIEND_ASSET_BUNDLE.md) | static product bundle contract |
| [HUGGING FACE](deploy/huggingface/README.md) | Docker Space and production deployment profiles |

## License

MIT — see [LICENSE](LICENSE).
