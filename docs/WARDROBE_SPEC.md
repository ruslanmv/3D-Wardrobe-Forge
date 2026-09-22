# Wardrobe manifest specification

A wardrobe is the list of looks an avatar has accumulated. It is what makes
Try-On Haul trivial on the client.

## Format

```json
{
  "schemaVersion": 1,
  "avatarId": "mira",
  "sourceHash": "abc123…",
  "sourceName": "Mira",
  "updatedAt": "2026-09-18T10:21:00Z",

  "looks": [
    {
      "id": "original",
      "name": "Everyday",
      "type": "source"
    },
    {
      "id": "look_burgundy",
      "name": "Burgundy Evening",
      "type": "vrmVariant",
      "vrmUrl": "/v1/assets/looks/look_burgundy/look.vrm",
      "previewUrl": "/v1/assets/looks/look_burgundy/preview.webp",
      "prompt": "elegant burgundy evening dress",
      "createdAt": "2026-09-18T10:20:41Z",
      "fitPassed": true
    },
    {
      "id": "look_cozy",
      "name": "Cozy Sunday",
      "type": "vrmVariant",
      "vrmUrl": "/v1/assets/looks/look_cozy/look.vrm",
      "previewUrl": "/v1/assets/looks/look_cozy/preview.webp",
      "prompt": "cozy oversized wool coat",
      "createdAt": "2026-09-18T10:25:02Z",
      "fitPassed": true
    }
  ]
}
```

## Rules

- `looks[0]` is always the `source` entry, and **cannot be removed**. Losing it
  would make the original avatar unrecoverable, which the pipeline treats as a
  correctness failure, not a convenience.
- `id` is unique within the wardrobe; re-generating a look replaces it in place.
- `fitPassed` mirrors the fit report's overall verdict, so a client can show or
  hide looks that only partly succeeded.
- `type` is `source` or `vrmVariant`. The type exists so future kinds (a
  material-only variant, say) do not break existing clients.

## Where it lives

| Location | Purpose |
| --- | --- |
| `WardrobeRepository` | the authoritative record (in-memory or JSON on disk) |
| `wardrobes/{avatarId}/wardrobe.json` in object storage | a fetchable copy |
| `output/wardrobe.json` from the CLI | written next to the generated VRM |

## Rendering for 3D-Avatar-Chatbot

`GET /v1/wardrobes/{avatarId}/avatars.json` renders the same wardrobe in the
shape `AvatarManager.initFromManifest` already parses:

```json
{
  "basePath": "https://forge.example.com",
  "items": [
    {
      "name": "Burgundy Evening",
      "file": "look.vrm",
      "url": "/v1/assets/looks/look_burgundy/look.vrm",
      "format": "vrm",
      "source": "3D-Wardrobe-Forge",
      "features": ["lipsync", "emotions", "gaze", "blink"],
      "notes": "elegant burgundy evening dress"
    }
  ]
}
```

The `features` list is asserted rather than measured: a derived look keeps the
source's humanoid rig and expressions — which stage 9 verifies — so whatever the
source supported, the look supports.

Only looks with a `vrmUrl` appear, which is why the `source` entry is omitted
from this rendering: the viewer already has the original avatar in its own list.

`WardrobeController.mergeIntoAvatarList()` consumes this endpoint to drop
generated looks straight into the viewer's avatar picker.
