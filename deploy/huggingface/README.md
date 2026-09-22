# Hugging Face deployment

The same FastAPI image used locally can run as a Hugging Face Docker Space. The recommended progression is:

- local development: `WARDROBE_PROFILE=local`
- public/demo Space: `WARDROBE_PROFILE=space`
- production endpoint or external orchestrated container: `WARDROBE_PROFILE=production`

A Space is appropriate for demos and low/medium traffic. Production should use durable object storage and a Redis-backed job queue. The `production` profile fails fast when memory jobs, local object storage, wildcard CORS, or unauthenticated API mode are selected.

## Docker Space

Create a Docker Space and copy `SPACE_README.md` to the Space repository as its root `README.md`. Mirror this repository's application files and Dockerfile, or configure your deployment automation to build from this repository.

Recommended Space variables/secrets:

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
