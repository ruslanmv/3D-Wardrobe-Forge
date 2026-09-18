# 3D-Wardrobe-Forge

AI-assisted wardrobe generation for VRM avatars.

**Goal:** accept a VRM avatar plus an outfit request and produce the same character wearing a new outfit as a validated VRM, together with preview images and fit metadata.

## Core contract

Input:

```json
{
  "avatar": {
    "url": "https://example.com/avatar.vrm",
    "sha256": "..."
  },
  "outfit": {
    "prompt": "elegant burgundy evening dress",
    "mode": "auto"
  }
}
```

Output:

```json
{
  "state": "completed",
  "look": {
    "id": "look_...",
    "name": "Burgundy Evening",
    "type": "vrmVariant",
    "vrmUrl": "https://cdn.example.com/look.vrm",
    "previewUrl": "https://cdn.example.com/preview.webp"
  },
  "fitReport": {
    "vrmValid": true,
    "humanoidValid": true,
    "weightsValid": true,
    "clippingCheck": "passed"
  }
}
```

## Architecture

- **FastAPI API** — job creation, status, wardrobe metadata.
- **Queue/worker** — long-running 3D jobs.
- **Blender headless worker** — imports VRM, fits garments, transfers weights, hides covered body geometry, exports VRM, renders preview.
- **Provider abstraction** — template-based garments first; optional Meshy/Tripo providers later.
- **Object storage** — generated VRM files, previews, fit reports.
- **JavaScript client** — designed to integrate with `ruslanmv/3D-Avatar-Chatbot`.

## Product strategy

The production path is intentionally **template-first**:

1. analyze the avatar;
2. parse the outfit prompt;
3. choose a robust garment template;
4. generate material/texture/style parameters;
5. fit it to the actual avatar;
6. transfer skin weights;
7. mitigate clipping;
8. validate and export a new VRM.

Fully AI-generated 3D garments are treated as an experimental provider behind the same interface.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then:

```bash
curl -X POST http://localhost:8080/v1/jobs \
  -H 'content-type: application/json' \
  -d '{
    "avatar": {
      "url": "https://example.invalid/avatar.vrm"
    },
    "outfit": {
      "prompt": "black date-night dress",
      "mode": "template"
    }
  }'
```

## Repository status

This scaffold implements the API/domain/provider contracts and a deterministic mock pipeline for development. Blender fitting/export scripts are organized and callable, but production-grade geometry fitting requires Blender + a VRM import/export add-on in the worker image.

## Roadmap

- M0 — API, domain model, storage/queue interfaces
- M1 — one known garment template -> one valid derived VRM
- M2 — automatic fitting across multiple body proportions
- M3 — garment library
- M4 — prompt-to-template styling
- M5 — external AI 3D providers
- M6 — `3D-Avatar-Chatbot` integration
- M7 — cached on-demand wardrobe generation

See `docs/ARCHITECTURE.md` and `docs/PIPELINE.md`.
