# Try-On integration: the contract 3D-Avatar-Chatbot relies on

F3. What the chatbot's Try-On (Together ▸ Try-On Haul, and the 👗 drawer) calls on
this service, what it reads back, and the settings a deployment needs. Anything
listed here is load-bearing: change it and the chatbot changes with it, in the same
release. `docs/3D_AVATAR_CHATBOT_INTEGRATION.md` is the older, general guide.

## Where Forge sits

**Artifacts are the product; generation is an optional service.** The chatbot works
completely from the wardrobe pack it ships in `vendor/wardrobe/` (produced by this
repository's `tools/export_default_wardrobe.py`, W12). A running Forge — a Hugging
Face Docker Space, or any host — only adds *creating* new looks. A completed job's
look is an artifact like any shipped one; after validation the chatbot does not care
where it came from.

So a Forge URL is a `baseUrl`, not a provider: nothing in the chatbot names Hugging
Face, and the same client works against Cloud Run, a private server or `localhost`.

## Routes

| Route | Used for | Limited (F1) |
| --- | --- | --- |
| `GET /health` | is it awake — a sleeping free Space answers slowly the first time | no |
| `GET /v1/capabilities` | engines, and `auth: {mode, keyRequired, trusted}` for *this* caller (F5) | no |
| `GET /v1/library` | the pinned avatars: `slug`, `sha256`, licence, `depictsAdult` | no |
| `POST /v1/library/{slug}/jobs` | dress a library avatar. Body: `{outfit, options, baseLookId?}` — never an avatar | **yes** |
| `POST /v1/generate` | dress an avatar the caller supplies (`avatar.url`, licence terms) | **yes** |
| `GET /v1/jobs/{id}` | poll a job to its end | no |
| `GET /v1/wardrobes/{avatar}` | the looks made for an avatar | no |
| `GET /v1/assets/{key}` | a look's files (`look.vrm`, `preview.webp`) | no |

The chatbot matches its five shipped avatars to library slugs by SHA-256
(`src/wardrobe/AvatarIdentity.js`), never by file name, and uses the library route for
them. Any other avatar goes through `/v1/generate` with its licence terms from the
Avatar Library.

## A job

`POST` answers `202` with a `JobRecord`. Poll `GET /v1/jobs/{id}` until `state` is one
of `completed`, `failed`, `rejected`. Working states, in order:

`queued` → `validating` → `analyzing-avatar` → `planning-outfit` → `generating-garment`
→ `fitting` → `skinning` → `resolving-clipping` → `exporting` → `validating-output` →
`rendering-preview`

A client shows an unknown state by name rather than dropping it. A completed job's
`look` is `{id, name, vrmUrl, previewUrl, sourceAvatarHash, sizeBytes}`; `vrmUrl` is
absolute when `PUBLIC_BASE_URL` is set, else relative to the Forge's own origin.

## Refusals

A rejected or failed job carries `reason`, one of `wardrobe.domain.jobs.FailureReason`.
The chatbot has a sentence for every one (`src/wardrobe/TryOnReasons.js`) and a test
that holds its list equal to this one — **add a reason here and add its sentence there
in the same release.** Transport answers: `401/403` → needs a key; `429` → busy, retry
after `Retry-After` seconds; network error or timeout → offline, shipped looks still work.

`requires_adult_declaration` is answered with a neutral sentence on purpose: whether an
avatar depicts an adult is its operator's declaration (`assets/library/policy.json`),
not something a page can supply, and Try-On never suggests a way round it.

## Deep link

`/studio/?avatar=<slug>` opens the Studio on that avatar; the Studio keeps the query
in step as the avatar changes. Try-On links "Open in Forge Studio" there.

## Deployment settings for a public Forge

```text
WARDROBE_ALLOWED_ORIGINS=["https://yourfriend.online"]    # CORS
WARDROBE_AUTH_MODE=api_key                                 # servers need the key…
WARDROBE_API_KEY=<secret>                                  # …as a Space secret, never in a page
WARDROBE_TRUSTED_ORIGINS=["https://yourfriend.online","https://www.yourfriend.online"]  # F5: pages need none
WARDROBE_RATE_LIMIT_PER_MINUTE=6                           # F1: jobs per visitor per minute
WARDROBE_QUEUE_CAP=8                                       # F1: jobs waiting or running at once
WARDROBE_FORWARDED_HOPS=1                                  # a Space is behind one proxy
PUBLIC_BASE_URL=https://<space>.hf.space
```

**No key belongs in a browser.** The chatbot's config has no field that should ever
hold a long-lived token for a public page; a deployment that must keep the Space
private puts the key in a server it controls — `deploy/proxy/` (F4) is a reference.

**A Space's disk is ephemeral.** Looks created there are for the session that made
them. A look worth keeping is exported as a pack (`GET /v1/wardrobes/{avatar}/pack.zip`,
or `tools/export_default_wardrobe.py` for the shipped set) and imported into the
chatbot, where it becomes an artifact with a hash; job storage is never the catalogue.
