# Reference proxy (F4)

`wardrobe-proxy.mjs` lets a public page use a Forge that the browser must not reach
directly. **Most deployments do not need it**: a public Space with the F5 trusted-origin
fallback and the F1 limits is already safe for yourfriend.online. Use this when the
Forge is private — a private Hugging Face Space, or `WARDROBE_AUTH_MODE=api_key` with
no trusted origins.

What it does, and why each part is there:

| | |
| --- | --- |
| Allow-list | Only Try-On's routes (`docs/TRY_ON_INTEGRATION.md`) pass. Admin, upload and every other route is 404, so the credential it holds can't be spent on them. |
| Credential | Adds `Authorization: Bearer $FORGE_TOKEN`; the browser's own `Authorization` and `Cookie` never reach the Forge. |
| Asset URLs | Rewrites the Forge's origin to `PUBLIC_URL` in JSON answers and proxies `/v1/assets/*`, so the 3D loader fetches a look with no auth header. |
| CORS | Answers only `ALLOWED_ORIGINS`; a preflight from anywhere else is 403. |
| Limits | Passes `X-Forwarded-For` through. Behind this proxy *and* a Space's own proxy, set the Forge's `WARDROBE_FORWARDED_HOPS=2`. |

```bash
FORGE_URL=https://you-3d-wardrobe-forge.hf.space \
FORGE_TOKEN=<Forge API key, or an HF token with read access for a private Space> \
PUBLIC_URL=https://wardrobe.example.com \
ALLOWED_ORIGINS=https://yourfriend.online,https://www.yourfriend.online \
PORT=8787 node deploy/proxy/wardrobe-proxy.mjs
```

Node 20, no dependencies. Point the chatbot's Forge `baseUrl` at `PUBLIC_URL`.

`FORGE_TOKEN` is a server secret: set it in the host's secret store, never in a file
in this repository, and never in a page.
