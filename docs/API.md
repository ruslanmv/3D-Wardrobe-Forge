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

## Product generation facade

### `POST /v1/generate` → `202`

A compact facade for browser and partner integrations. It creates the same underlying job as `POST /v1/jobs`; there is no second generation pipeline.

```json
{
  "avatar": {"storageKey": "sources/abc123/mira.vrm", "avatarId": "mira"},
  "prompt": "elegant burgundy evening dress",
  "mode": "auto",
  "options": {"renderPreview": true, "engine": "auto", "wardrobeId": "mira"}
}
```

```json
{
  "jobId": "job_01J…",
  "status": "queued",
  "statusUrl": "/v1/jobs/job_01J…",
  "eventsUrl": "/v1/jobs/job_01J…/events"
}
```

Hosted deployments can protect all `/v1` routes with bearer authentication by setting `WARDROBE_AUTH_MODE=api_key` and `WARDROBE_API_KEY`. Health remains public.

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

## Garment catalog and styling for HomePilot

New endpoints for real template previews and queued customization:

| Endpoint | Returns |
| --- | --- |
| `GET /v1/catalog/garments[?category=top]` | Public-safe garment groups with real-preview status |
| `GET /v1/catalog/garments/{templateId}/preview` | Cached WebP if generated, otherwise 404 |
| `POST /v1/catalog/customize` | Real async job, same progress and validation as `/v1/generate` |

The public catalog does not advertise restricted garments or nonexistent
previews, and browsing never triggers rendering jobs. `includeRestricted=true`
is only available to an active admin session; it does not override job policy.
Pre-generate approved previews via `tools/catalog/render_templates.py`.
See [GARMENT_CATALOG_API.md](GARMENT_CATALOG_API.md) for examples and Space deployment.

## Looks, templates and assets

| Endpoint | Returns |
| --- | --- |
| `GET /v1/looks/{id}` | one completed look |
| `GET /v1/templates[?category=dress]` | the garment library |
| `GET /v1/templates/{id}` | one template |
| `GET /v1/assets/{key}` | a stored artifact (local backend; S3 issues signed URLs) |

## Outfit dictionary (OD1)

### `GET /v1/outfits`

Named sets a client may offer — the chatbot's companion answers "what can you
wear?" from this, and its Try-On tabs are its groups. Each entry is shorthand
for a request someone could type and grants nothing; a job for it is planned,
fitted and gated as if typed.

```json
{
  "version": 1,
  "groups": [{"id": "casual", "title": "Casual", "private": false}, …],
  "outfits": [
    {
      "id": "little-black-dress", "title": "Little black dress", "group": "dressy",
      "prompt": "black satin cocktail dress",
      "request": {"prompt": "black satin cocktail dress"},
      "tags": ["evening"], "rating": "general", "slots": ["dress"],
      "garments": [{"name": "…", "category": "dress", "template": "dress-cocktail-v1",
                    "slot": "dress", "adultGate": false}]
    }, …
  ]
}
```

- `request` is the exact `outfit` body a job sends (with a look or hosiery
  `preset` when the set needs one, e.g. the stockings group).
- `rating` is computed from Forge's planner and adult gate — `private` when any
  garment needs an adult declaration (an intimate category, a template that says
  so, or see-through fabric). Never written by hand; a group's `private` flag is
  a claim the tests check against it both ways, and an integration test checks
  every entry against the gate a real job meets.
- Source: `wardrobe/pipeline/outfit_dictionary.py`. Every entry was also
  generated on the declared-adult fit form and passed its fit checks.

## Independent collections (AB3)

A collection is a folder under `assets/collections/` with its own ids, its own
dictionary group and its own previews; nothing in it replaces a template, an
entry or an occasion that existed. See [ANIME_BEACHWEAR](ANIME_BEACHWEAR.md).

### `GET /v1/collections`

```json
{"collections": [{"id": "anime-beachwear", "title": "Anime Beachwear",
                  "subtitle": "Japanese Anime-Inspired Swimsuits", "occasion": "Beach & Pool",
                  "categories": ["Bikini", "One-Piece", "Sporty", "Kawaii", "Beach Glamour"],
                  "designs": 12}]}
```

### `GET /v1/collections/{id}`

The collection record with each design's `rating` (computed, as in the outfit
dictionary) and `request` — the exact `outfit` body a job sends:

```json
{"prompt": "…", "design": {"collection": "anime-beachwear", "id": "beach-violet-halter"}}
```

A job may add `"color"` (one of the collection's `customize.colours` names) and
`"finish"` (`matte`, `satin` or `gloss`) to the `design` block. An unknown
collection or design is a `422` before any job exists. A design job is planned,
fitted, gated and licensed like any other job: swimwear needs the adult
declaration, and a model whose terms disallow sexual usage refuses it.

### `GET /v1/collections/{id}/previews/{file}`

The front, side and back pictures (`<design>-front.webp` …). File names are
checked against `^[a-z0-9][a-z0-9-]{0,80}\.(webp|png)$`; anything else is `404`.

## Body surface (BS1)

### `GET /v1/body-surface/profiles`

```json
{"version": 1, "adultEnabled": false,
 "profiles": [{"id": "collision-reference", "title": "Collision body (reference)",
               "capability": "body_collision", "regions": []}, …]}
```

Ids, titles, capabilities and region names only. A job names one as
`bodySurface: {"profileId": "…", "detailLevel": "garment-fitting" | "render"}`
(a sibling of `outfit`), and may add `options.clothRelaxation: "xpbd"`. An
unknown profile is `rejected` with `body_surface_profile_unavailable`; an adult
profile refused by the model's terms, the operator's switch
(`WARDROBE_ADULT_BODY_SURFACE`) or the missing declaration is `rejected` with
`body_surface_not_permitted`. The fit report then carries `bodySurface`
(profile, regions made or not and why, collision envelope, per-layer signed
clearance) and, per layer, any `relaxation`. See
[BODY_SURFACE](BODY_SURFACE.md).

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
