# Hugging Face deployment

The same FastAPI image used locally can run as a Hugging Face Docker Space. The recommended progression is:

- local development: `WARDROBE_PROFILE=local`
- public/demo Space: `WARDROBE_PROFILE=space`
- production endpoint or external orchestrated container: `WARDROBE_PROFILE=production`

A Space is appropriate for demos and low/medium traffic. Production should use durable object storage and a Redis-backed job queue. The `production` profile fails fast when memory jobs, local object storage, wildcard CORS, or unauthenticated API mode are selected.

## Docker Space

The Space is [ruslanmv/3D-Wardrobe-Forge](https://huggingface.co/spaces/ruslanmv/3D-Wardrobe-Forge). Deploy with:

```bash
HF_TOKEN=hf_... make space                        # or: sh deploy/huggingface/deploy.sh
HF_TOKEN=hf_... HF_SPACE_REPO=you/your-space make space
DRY_RUN=1 make space                              # stage only, and list what would go
```

`deploy.sh` uploads the **committed HEAD**, not the working tree: a `git archive` of
exactly what the Dockerfile copies (`Dockerfile`, `pyproject.toml`, `LICENSE`,
`apps`, `wardrobe`, `worker`, `tools`, `assets`), with `SPACE_README.md` as the
Space's root `README.md` — its front matter is what makes it a Docker Space on
port 8080. The upload mirrors, so files removed here are removed there, and the
Space commit names the source commit. It then sets the Space variables
`WARDROBE_PROFILE=space`, `WARDROBE_JOB_CONCURRENCY=1` and `PUBLIC_BASE_URL` (read
from the Space's domain). Use a write token, and prefer a fine-grained one scoped
to the Space.

The Space builds the image itself; the first build takes a few minutes, most of
it `pip install` and fetching the avatar library.

Out of the box the Space is an open demo (`WARDROBE_AUTH_MODE=none`). To require
a key, add `WARDROBE_AUTH_MODE=api_key` as a variable and `WARDROBE_API_KEY` as a
**secret** in the Space settings; the Studio's key button then asks for it.

Variables for a keyed or cross-origin Space:

```text
WARDROBE_PROFILE=space
WARDROBE_ENGINE=native
WARDROBE_PROVIDER=template
WARDROBE_JOB_BACKEND=memory
WARDROBE_STORAGE_BACKEND=local
PUBLIC_BASE_URL=https://<space-subdomain>.hf.space
WARDROBE_ALLOWED_ORIGINS=["https://yourfriend.online"]
WARDROBE_AUTH_MODE=api_key
WARDROBE_API_KEY=<secret>
```

For a public demonstration without private avatars you may set authentication to `none`, but do not use that configuration for a paid or multi-tenant service.

## Wardrobe Studio

The image serves an editor at `/studio/`, and `/` redirects there, so opening the
Space opens the Studio. It is static and build-free — Three.js and three-vrm load
from jsDelivr, pinned to the versions yourfriend.online ships — and it talks only
to this deployment's `/v1` API.

**The avatar library is fetched when the image is built.** `tools/fetch_library.py`
downloads yourfriend's five CC0 avatars and checks each against the SHA-256 pin in
`assets/library/models.json`, a verbatim copy of yourfriend's own provenance
manifest. A mismatch fails the build. The files are not committed: 67 MB of
binaries, and a Space refuses plain-git files over 10 MB. Build with
`--build-arg FETCH_LIBRARY=0` for an API-only image.

**Library avatars need no licence prompt, and the browser cannot supply one.**
All five embed `modification: unknown` in their VRM metadata, so under strict
licensing a plain `POST /v1/jobs` on them is refused with 428. The Studio uses
`POST /v1/library/{slug}/jobs` instead, where the server fills in the avatar and
the conditions its provenance manifest grants (`CC0` → modification and
redistribution allowed). An embedded prohibition is still checked first and
still wins.

**With `WARDROBE_AUTH_MODE=api_key`**, the Studio's key button stores the key in
that browser and sends it as a Bearer token. Every asset — avatar, look,
preview — is fetched with it, so a keyed Space works the same as an open one.

**Exporting.** `GET /v1/wardrobes/{avatar}/bundle.zip` (`?passedOnly=true` to drop
looks whose fit failed) is the Studio's Export button. Unzip it into
3D-Avatar-Chatbot's `vendor/wardrobe/`, or yourfriend.online's static wardrobe.

**The container runs as uid 1000.** Hugging Face runs Docker Spaces as uid 1000
regardless of `USER`; the image creates that user and gives it `/data/wardrobe`.

**Storage is ephemeral on a free Space.** Looks live in `/data/wardrobe` and the
wardrobe index is in memory, so a restart empties every wardrobe. Export what you
want to keep. Attaching persistent storage and a durable job backend is the
production profile below.

## Production

Use Redis plus S3/R2-compatible storage:

```text
WARDROBE_PROFILE=production
WARDROBE_JOB_BACKEND=redis://...
WARDROBE_STORAGE_BACKEND=s3
S3_ENDPOINT=...
S3_BUCKET=...
WARDROBE_ALLOWED_ORIGINS=["https://yourfriend.online"]
WARDROBE_AUTH_MODE=api_key
WARDROBE_API_KEY=...
```

Do not embed the API key into a public browser bundle. Prefer a short-lived token or a yourfriend.online backend proxy for production traffic.
