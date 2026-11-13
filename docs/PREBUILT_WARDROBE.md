# Prebuilt wardrobe: every garment, every character, ready before she is asked

Design, 2026-11-13. Batch prefix `PB`. PB1–PB3 and the PB4 storage are implemented (see
"Status" at the end); switching the Space over is a settings change.

## The problem, measured

In a Private conversation she offered lingerie, the person said yes, and she
answered "No tengo lencería guardada" ("I have no lingerie saved"), then offered
an unrelated saved look ("Black Bodycon Mini Dress + Black Glossy Stiletto Ankle
Boots"). Two things caused it:

1. **She can only offer what is already made.** The app's in-scene wardrobe
   (`InSceneWardrobe.plan` → `OutfitDecisionEngine.choose`) chooses from the
   looks she has. Anything else is a Forge job the person must approve and then
   wait for — about three minutes on the public Space.
2. **The wait is not generation.** On a local Forge the same jobs finish in
   **6–10 s** (twelve jobs measured on 2026-11-13: 6.0–10.3 s each). The rest is
   the Space's shared CPU and queue, a cold start, and downloading a 12–15 MB
   look VRM.

So the fix is not a faster pipeline. It is to have made every look before the
conversation needs it, and to answer a request from storage.

## The size of "everything"

| Item                                             | Count / size                                   |
| ------------------------------------------------ | ---------------------------------------------- |
| Catalog templates (public 62 + adult 43)         | 105                                            |
| Library characters (`assets/library`, declared)  | 8                                              |
| Looks per colour                                 | 105 × 8 = **840**                              |
| One look VRM                                     | 12–15 MB                                       |
| Storage per colour                               | about **11 GB**                                |
| Build time per colour (8 s/job)                  | about 2 h on one runner; ~15 min on 8 runners  |

All five colours would be 4,200 looks and ~55 GB. The first version prebuilds
each template in its **default colour** only; another colour is the existing
FC2 recolour, made on request and then stored like any other look (below).

## Where the looks live

**Decision (2026-11-13): a private Hugging Face dataset.** Measured: a look is 12.2–15.4 MB
(average 13.7 MB, ~90% of it her body), so 105 × 8 is ~11.5 GB. Git and Git LFS are out (LFS's
free quota is about 1 GB of storage and 1 GB of download a month). A dataset is private, reads
with the Space's existing `HF_TOKEN`, and needs no new account; `WARDROBE_STORAGE_BACKEND=hf`
(`HfDatasetObjectStore`) reads a file from it once and keeps it on local disk. The S3 option
below still works unchanged for anyone who prefers a bucket.

**Not in either git repository.** Neither `3D-Avatar-Chatbot` nor this repo
holds look files. They live in Forge's object store, which already has an S3
backend (`wardrobe/storage/object_store.py`, `WARDROBE_STORAGE_BACKEND=s3`,
presigned URLs included):

- **Recommended: a private S3-compatible bucket** (Cloudflare R2: no egress
  fees, which matters for 12 MB downloads). Adult looks must never sit in a
  public bucket; the bucket is private and the Space hands out short-lived
  presigned URLs only to the requests the policy already allows.
- Alternative: a private Hugging Face dataset repo read by the Space with its
  `HF_TOKEN`. Simpler to start, slower to serve, and needs a small object-store
  adapter that does not exist yet.

The app keeps asking Forge exactly as it does today. It never learns where the
bytes are.

## The cache key

A prebuilt look is reusable only while everything that shaped it is unchanged:

```
key = sha256(
  avatar source hash        # the pinned VRM bytes of the character
  template id
  template fingerprint      # the template file's content hash
  colour                    # null = template default
  options that change bytes # stance, foundation colour, engine
  PIPELINE_VERSION          # bumped by hand when fitting/assembly output changes
)
```

`PIPELINE_VERSION` is an explicit constant in `wardrobe/pipeline/`, bumped in
the same commit as any change that alters output geometry. Hashing the whole
`wardrobe/` tree would rebuild 840 looks for a typo in a comment.

The index is one JSON object per character in the store
(`prebuilt/<avatar-hash>/index.json`: key → look id, template, colour, private,
built-at, Forge commit), so a lookup is one small read.

## Serving: a cache in front of the queue

`Orchestrator.submit` checks the index before it queues anything:

- **Hit**: return a `JobRecord` already `completed`, pointing at the stored
  look, with `cache: "prebuilt"`. Same response shape the app already polls, so
  the app gets an answer on its first poll — no app change needed for speed.
- **Miss**: queue the job as today. When it succeeds, write the look and its
  key into the index. The second person to ask gets a hit.

The policy runs **before** the lookup, exactly as now: a restricted template on
an avatar not declared adult is refused whether or not a prebuilt look exists.
A hit for a private look returns a presigned URL only to a request that would
have been allowed to make it.

New characters and custom uploads have no prebuilt looks; every first request
is a miss, generated once and cached from then on. Optionally, the first time a
new source hash is seen, Forge queues a background warm-up of the 20 most-asked
templates at low priority.

## The CI job: `prebuild-wardrobe.yml`

Runs on every push to `main` (after `ci.yml` passes) and on manual dispatch.

1. **Plan.** Load the catalog and library; compute every key; read the index;
   list only the missing keys. A push that changes one template rebuilds 8
   looks, not 840. A `PIPELINE_VERSION` bump rebuilds everything.
2. **Build.** A matrix with one job per character (8 jobs). Each runs the
   pipeline in-process (`Orchestrator.run_now`, no HTTP), uploads each look to
   the bucket, then writes its index entries. Failures are recorded per key with
   the reason and never block the other keys.
3. **Verify.** Re-read the index; every key in the plan is either present or
   listed as failed. Post the counts in the job summary (built, reused, failed,
   bytes uploaded).
4. **Prune.** Looks whose key no longer appears in any plan are deleted after a
   grace period (7 days), so a rollback can still hit the old ones.

Secrets: the bucket credentials (`S3_*`). The Space reads the same bucket with
read-only credentials. Nothing is committed.

The Space deploy (`deploy-space.yml`) does not wait for the prebuild: until a
key is built, it is a miss and generated on demand, as today.

## What changes in the app (3D-Avatar-Chatbot)

Speed needs no app change. Two small changes fix the conversation itself:

1. **Prebuilt looks count as hers.** `InSceneWardrobe` adds the character's
   prebuilt index (a new `GET /v1/library/{slug}/prebuilt` returning template,
   colour, look id) to the looks `OutfitDecisionEngine.choose` sees, marked
   ready. "Lingerie" then matches a real lingerie look, worn at once with no
   approval step, because nothing is being generated.
2. **A yes is answered with what was offered.** When she offers a category
   (lingerie) and none is ready, the follow-up offer must be that category —
   made on request — never the nearest unrelated saved look.

## Phases

| Phase | Deliverable                                                                         | Done when                                                                       |
| ----- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| PB1   | Cache key, `PIPELINE_VERSION`, index read/write, hit/miss in `Orchestrator.submit` | A repeated identical request returns `completed` with `cache: "prebuilt"` in < 1 s |
| PB2   | `tools/prebuild.py` (plan / build / verify) run locally against a bucket            | 840 looks built and indexed from a laptop; rerun builds 0                        |
| PB3   | `prebuild-wardrobe.yml` matrix on push to `main`                                    | A template change rebuilds only its 8 looks                                     |
| PB4   | Space on the private bucket with presigned URLs                                     | Public Space answers a prebuilt lingerie request on the first poll              |
| PB5   | App: prebuilt looks in `InSceneWardrobe`; matching follow-up offer                  | "¿Quieres lencería?" → "Sí" puts lingerie on her with no wait                   |

## Later, not in this design

Each look stores the whole character (~10 MB of the 12–15 MB is her body).
Storing garment-only meshes per character and assembling them in the browser
would cut storage about tenfold and make every colour cheap. That changes the
app's loader and the cloth contract, so it waits until PB1–PB5 are in use.

## Status (2026-11-13)

| Phase | State | Where |
| ----- | ----- | ----- |
| PB1 cache key, hit/miss in `submit`, remember on completion | done, tested | `wardrobe/pipeline/prebuilt.py`, `Orchestrator.submit` |
| PB2 per-character ready list, `GET /v1/library/{slug}/prebuilt`, `tools/prebuild.py` | done, tested | `apps/api/routes/studio.py`, `tools/prebuild.py` |
| PB3 CI on push to `main` | written; needs `vars.WARDROBE_HF_DATASET` | `.github/workflows/prebuild-wardrobe.yml` |
| PB4 dataset store; her wardrobe lists prebuilt looks after a restart | done, tested; Space needs `WARDROBE_STORAGE_BACKEND=hf` and `WARDROBE_HF_DATASET` | `HfDatasetObjectStore`, `GET /v1/wardrobes/{id}` |
| PB5 Private names every kind she has ready | done (3D-Avatar-Chatbot `ac44d59`) | `PrivateActionBridge.closetSummary` |

The app needs no change to see prebuilt looks: it already reads her library wardrobe, and that
wardrobe now includes them.

To turn it on: create the dataset (or let the workflow create it, private), set the repository
variable `WARDROBE_HF_DATASET`, run "Prebuild wardrobe" once from the Actions tab, then set the
same two values on the Space (`WARDROBE_STORAGE_BACKEND=hf`, `WARDROBE_HF_DATASET=...`; its
`HF_TOKEN` secret needs read access to the dataset).
