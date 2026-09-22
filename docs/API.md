# HTTP API

Base path `/v1`. All request and response bodies are JSON in **camelCase**.
Interactive docs are served at `/docs`; the schema is at `/openapi.json`.

## Service

### `GET /health`

```json
{ "ok": true, "service": "3D-Wardrobe-Forge", "version": "0.2.0" }
```

### `GET /v1/capabilities`

What *this* deployment can do, so the client can adapt rather than guess.

```json
{
  "version": "0.2.0",
  "engines": {
    "native": true, "blender": false, "default": "auto",
    "bodyMasking": false, "generatedMeshes": false
  },
  "provider": "template",
  "templates": 17,
  "categories": ["dress", "jacket", "shoes", "skirt", "top", "trousers"],
  "outputVersions": ["source", "VRM0", "VRM1"],
  "maxAvatarBytes": 134217728,
  "strictLicensing": true
}
```

## Avatars

### `POST /v1/avatars/inspect`

`multipart/form-data` with `file`. Reports what the VRM contains and whether we
may modify it — **without** creating a job. Use it to warn the user early.

```json
{
  "analysis": {
    "spec": "VRM1",
    "title": "Mira",
    "humanoidBones": { "hips": 0, "head": 5, "...": 0 },
    "measurements": { "heightM": 1.62, "shoulderWidthM": 0.359, "confidence": {"shoulder": 1.0} },
    "license": { "modification": "allowed_with_redistribution", "commercialUsage": "allowed" },
    "expressions": ["aa", "angry", "blink", "..."],
    "sha256": "abc123…"
  },
  "usable": true,
  "license": { "allowed": true, "requiresAttestation": false, "message": "source model permits modification" }
}
```

### `POST /v1/avatars` → `201`

`multipart/form-data` with `file`. Stores the VRM and returns a `storageKey`.
Preferred over passing a URL: the avatar never has to be publicly reachable,
and the same upload can back many looks.

```json
{ "storageKey": "sources/abc123…/mira.vrm", "sha256": "abc123…", "sizeBytes": 4821004, "analysis": { } }
```

## Jobs

### `POST /v1/jobs` → `202`

```json
{
  "avatar": {
    "storageKey": "sources/abc123…/mira.vrm",
    "sha256": "abc123…",
    "avatarId": "mira",
    "name": "Mira",
    "license": {
      "conditionsOfUse": { "modification": "allow", "redistribution": "disallow" },
      "userAttestsModificationAllowed": false
    }
  },
  "outfit": {
    "prompt": "elegant burgundy evening dress with subtle gold details",
    "mode": "auto"
  },
  "options": {
    "outputVersion": "source",
    "renderPreview": true,
    "engine": "auto",
    "wardrobeId": "mira"
  }
}
```

`avatar` accepts `url` **or** `storageKey`. `outfit.mode` is `auto` (default),
`template` or `generated`. `conditionsOfUse` takes the VRoid Hub shape
3D-Avatar-Chatbot's VRM Manager already stores, verbatim.

Immediate response:

```json
{ "id": "job_01J…", "state": "queued", "createdAt": "…", "events": [ … ] }
```

### `GET /v1/jobs/{id}`

The full record: `state`, `events`, `analysis`, `plan`, `look`, `fitReport`,
`error`, `reason`.

When complete:

```json
{
  "id": "job_01J…",
  "state": "completed",
  "look": {
    "id": "look_01J…",
    "name": "Burgundy Evening",
    "type": "vrmVariant",
    "vrmUrl": "/v1/assets/looks/look_01J…/look.vrm",
    "previewUrl": "/v1/assets/looks/look_01J…/preview.webp",
    "sourceAvatarHash": "abc123…",
    "sizeBytes": 50236
  },
  "fitReport": {
    "vrmValid": true,
    "humanoidValid": true,
    "weightsValid": true,
    "skeletonPreserved": true,
    "expressionsPreserved": true,
    "sourceRecoverable": true,
    "clippingCheck": "passed",
    "previewRendered": true,
    "engine": "native",
    "garmentVertices": 297,
    "garmentTriangles": 576,
    "bonesUsed": ["chest", "hips", "spine", "…"],
    "poseTests": { "passed": true, "sit": { "maxEdgeStretch": 1.6, "passed": true } },
    "warnings": []
  }
}
```

### `GET /v1/jobs/{id}/events` — Server-Sent Events

One message per state change, with past events replayed on connect so a late
subscriber still sees the whole run.

```
event: fitting
data: {"state":"fitting","progress":0.45,"message":"fitting the garment with the native engine"}

event: completed
data: {"state":"completed","progress":1.0,"message":"look ready"}
```

### `GET /v1/jobs?limit=25`

Recent jobs, newest first.

## Looks, templates and assets

| Endpoint | Returns |
| --- | --- |
| `GET /v1/looks/{id}` | one completed look |
| `GET /v1/templates[?category=dress]` | the garment library |
| `GET /v1/templates/{id}` | one template |
| `GET /v1/assets/{key}` | a stored artifact (local backend; S3 issues signed URLs) |

## Wardrobes

| Endpoint | Returns |
| --- | --- |
| `GET /v1/wardrobes` | avatar ids that have a wardrobe |
| `GET /v1/wardrobes/{avatarId}` | the wardrobe manifest |
| `GET /v1/wardrobes/{avatarId}/avatars.json` | the wardrobe as a **3D-Avatar-Chatbot avatar manifest** |
| `DELETE /v1/wardrobes/{avatarId}/looks/{lookId}` | remove a look (never the source) |

## Status codes

| Code | When |
| --- | --- |
| `202` | job accepted |
| `400` | source could not be fetched |
| `413` | source over the size limit |
| `422` | not a VRM, not humanoid, hash mismatch, invalid request |
| `428` | usage terms unknown — supply an attestation |
| `451` | the model's own terms prohibit modification |
| `502` | the AI mesh provider failed |

Error bodies carry the stable code:

```json
{ "detail": { "reason": "requires_user_license_attestation", "message": "…" } }
```
