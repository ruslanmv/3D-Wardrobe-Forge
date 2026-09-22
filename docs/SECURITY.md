# Security and privacy

A user-uploaded VRM is an **untrusted binary** that a parser — and possibly
Blender — will read. It is also **personal data**: it is a model of someone's
character, often of themselves.

## Threat model

| Threat | Mitigation |
| --- | --- |
| Malformed model crashes or hangs the parser | strict GLB parsing with bounds checks and a cycle guard on the node graph |
| Decompression / allocation bomb | hard size cap enforced while streaming, plus a parser-level ceiling |
| SSRF via `avatar.url` | scheme allowlist (https), optional host allowlist, DNS resolution checked against private/loopback/link-local/reserved ranges, **redirects refused** |
| Path traversal via storage keys | keys matched against a strict pattern; resolved paths must stay under the storage root |
| Command injection via a prompt | no shell anywhere; Blender is launched with `create_subprocess_exec` and an argument list |
| Prompt reaching a third party unexpectedly | prompts leave the service only for `outfit.mode="generated"`, which is opt-in per request |
| Runaway Blender process | bounded timeout, killed on overrun, output captured |
| Generated avatars readable by others | local backend serves from a private path; S3 backend issues time-limited signed URLs |
| Model retained longer than wanted | source and scratch files deleted after every job by default |

## Input validation order

Cheapest and most decisive checks first, so a bad file never reaches the
expensive stages:

```
URL policy → size (streamed) → GLB magic → sha256 → glTF parse
  → VRM extension → licence gate → humanoid validation → geometry
```

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAX_AVATAR_BYTES` | 128 MiB | source size cap |
| `MAX_OUTPUT_BYTES` | 256 MiB | refuse to publish a larger result |
| `ALLOWED_SOURCE_SCHEMES` | `["https"]` | plain HTTP is rejected |
| `ALLOWED_SOURCE_HOSTS` | `[]` | empty means any public host |
| `BLOCK_PRIVATE_NETWORKS` | `true` | SSRF guard |
| `FETCH_TIMEOUT_S` | 60 | source download timeout |
| `BLENDER_TIMEOUT_S` | 900 | hard kill for the subprocess |
| `DELETE_SOURCE_AFTER_JOB` | `true` | wipe the job workdir when done |
| `STRICT_LICENSING` | `true` | unknown terms require an attestation |

An unresolvable hostname is treated as **unsafe**, not as "probably fine".

## Worker isolation

The Blender worker parses untrusted models, so in `docker-compose.yml` it runs
with `no-new-privileges` and `cap_drop: ALL`, as a non-root user (uid 10001),
with no inbound ports. In a real deployment, give it no outbound network access
either unless an AI mesh provider is enabled.

Both images run as a non-root user.

## Privacy

- Generated looks are **private by default**. Nothing is world-readable.
- The source VRM and every scratch file are deleted when a job ends. Turn that
  off (`DELETE_SOURCE_AFTER_JOB=false`) only for debugging.
- Prompts are stored on the job record and in the wardrobe manifest, because a
  user needs to know what a look was made from. They are not sent anywhere
  unless `outfit.mode="generated"`.
- `sha256` of the source is recorded so a derived look can be traced back to
  its origin, and stored in the output's `extras.wardrobeForge`.
- The API sets permissive CORS so a browser client on another origin can call
  it. **Put authentication in front of it before exposing it publicly** — this
  service has no built-in authn/authz.

## Reporting a vulnerability

Open a security advisory on the repository rather than a public issue.
