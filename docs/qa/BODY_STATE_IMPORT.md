# Body-state import, read grants, and the jeans hip split

2026-11-15, Forge `claude/funny-shannon-mh185b` on top of `ultimate` @ `06ea379`. Batches BI1
(operator body-state import), BI2 (read grants), BI4 (no private look in a public
dataset), KL1 (bottoms under a kept top), and the
repair of eight catalogue tests that failed on clean `06ea379`.

## BI1. Import an operator-supplied body state

`POST /v1/admin/library/{slug}/body-states` (admin session only; multipart):

| Field | Required | Meaning |
|---|---|---|
| `file` | yes | the VRM bytes (no URL field; at most 64 MB) |
| `state` | yes | `lingerie` or `bare` |
| `sourceSha256` | yes | the library file it was made from; must equal the pinned hash |
| `sha256` | no | the uploaded file's hash as the operator has it; a mismatch refuses before parsing |
| `licence` | yes | the terms the operator holds it under (recorded, not a permission) |
| `rightsAttested` | yes | `true`: the operator attests they hold those rights (recorded) |
| `name` | no | the look's name in her wardrobe |
| `garments` | no | catalogue template ids, used only when the file carries no Forge garment tags |

`wardrobe/body_surface/body_state_import.py: check()` answers every question and reports all of
them (`verdict.checks`), refusing with a stable reason:

| Check | Refusal |
|---|---|
| stated SHA-256 = actual | `sha256-mismatch` |
| bound to her pinned hash; not her original bytes | `source-mismatch`, `same-as-original` |
| GLB, VRM, same spec, usable humanoid with skins | `not-a-vrm`, `spec-mismatch`, `rig-invalid` |
| every humanoid bone: same node name, within 1 mm | `rig-mismatch` |
| every expression she has | `expressions-lost` |
| VRM title (hers, or Forge's `"<hers> — <look>"`) and authors | `identity-mismatch` |
| face and hair: every primitive skinned mostly to her head, same vertex and morph counts, positions within 0.1 mm | `identity-mismatch`, `identity-unverifiable` |
| `bare`: no detected clothing, body closed in every `body-bare-v1` band | `clothing-remains`, `body-incomplete` |
| eligibility, for her file **and** the uploaded file | `not-permitted` |

Eligibility is `eligibility.assess`, the contract `body-bare-v1` uses. `lingerie` needs the
author's permission, the adult declaration and a private result (what Forge already requires to
make lingerie). `bare` additionally needs `WARDROBE_ADULT_BODY_SURFACE` and a clearly-adult
design review recorded for **both exact files** (her source and the import). Nothing here reads
a review from the request or writes either registry.

Accepted: the private marker is written first (naming her wardrobe), then `look.vrm`, then
`import.json` (the verdict, the provenance, who imported it), then her prebuilt list gets an entry
with `origin: operator-import`, `wardrobeState`, `sourceSha256`, `outputSha256` and the garments
read from the file. All of it is in the store, so it survives a restart (tested with a new
process over the same storage). `GET` lists her imports; `DELETE …/{lookId}` withdraws one (list
entry, files, marker last). A re-upload of the same bytes is the same look.

Real asset (local Forge, AvatarSample A, a black satin chemise Forge built): all 11 checks pass,
83 face/hair primitives within tolerance, 54 bones, 15 expressions, garments
`under-chemise-satin-v1` read from the file. The same file refused as: wrong stated hash
(`sha256_mismatch`), bound to AvatarSample B (`rig_mismatch`, every bone moved), `bare`
(`clothing_remains: onepiece, shoes`).

Found while doing it: Forge titles every look `"<her title> — <look name>"`, so the first real
import was refused as another character. Only that exact form is accepted (tested).

## BI2. Read grants: no admin token in a consumer

Before BI2 a private look was listed and served to an admin session only, so the only way the
companion app could ever show one was to hold the admin token, which also declares, imports,
builds and deletes. `wardrobe/policy/grants.py`:

- `POST /v1/admin/grants {slugs, ttlSeconds, label}` (admin only) → a token sent as
  `X-Wardrobe-Grant`.
- HMAC-SHA256 over `{scope: private-read, slugs, iat, exp, jti}` with `WARDROBE_GRANT_SECRET`
  (≥ 32 characters). Unset: no grants, private looks stay admin-only, exactly as before.
- At most 30 days; revoke one with `WARDROBE_GRANT_REVOKED=<id>,…`, all by rotating the secret.
- Read-only: `GET /v1/wardrobes/{slug}`, `GET /v1/library/{slug}/prebuilt` and `/v1/assets/…`
  accept it for the avatars it names. `/v1/assets` checks the wardrobe named in the look's own
  private marker, a stored object. A marker written before BI2 names none and stays admin-only.
- No write route accepts it (tested: import, mint, declare, withdraw all answer 401).

## BI4. Private looks are not published to a public dataset

`dataset_publish.publish` (CI's `tools/publish_prebuilt.py`, and the Space's own dataset store)
sent every prebuilt entry's files and every wardrobe list whole. A private look built through
the pipeline (every bare prebuild is private) therefore went to the dataset with its VRM, and a
private list item with it. Now a private look (its `private.json` marker, or a private request
in its entry) and every private list item go up only when the hub reports the dataset private
(`repo_info().private`), or when `--include-private` says so. Anything else, including no
answer, counts as public: they stay in local storage and are returned as `privateHeldBack`.
Consequence on a Space whose dataset is public: its private looks do not survive a restart
(local disk only). Make the dataset private to keep them.

## KL1. The jeans hip split

AvatarSample A keeps her cardigan when she is given straight jeans. The jeans were fitted to her
body alone and drawn over the cardigan, and its ribbed hem came through the denim in a jagged
band all round her hips. `wardrobe/geometry/kept_layers.py: tuck_under_kept_tops` (called by the
native engine after the shell is built) moves a `trousers`, `shorts` or `skirt` vertex that is
inside a kept top's height span and outside its inner surface radially to 4 mm inside it, never
closer than 3 mm to her skin; a vertex with no room is left and counted (`noRoom`). Heights are
never changed, the kept top is never moved. Rendered in the app before and after (front, side,
back, close-ups): the band is gone and the cardigan hangs over the jeans. What is left: a faint
line on the denim just under the hem, where tucked vertices meet untouched ones.

**`PIPELINE_VERSION` was not bumped.** KL1 changes the bytes of new bottoms built under a kept
top. Bumping would make every cached look a miss (~1900 looks rebuilt) and break the historic
cache keys the P0 list asks to keep. Cached bottoms on the characters whose own top stays on
(AvatarSample A, B, C, O and Model Girl have a `tops` slot; VRoid F/M and Rinna have no
removable clothing) therefore keep the split until rebuilt. Measured on A only. That is a decision for the
operator: bump in its own commit, or rebuild only those looks.

## Eight catalogue tests that failed on clean `06ea379`

Reproduced on a pristine worktree at `06ea379`: `test_haul_pipeline::test_every_template_…`,
`test_underwear_audit::…audited_once`, two in `test_pack`, two in `test_palettes`,
`test_parameter_schema[body-bare-v1]`, `test_templates::test_procedural_meshes_are_flagged`.
Seven iterated `body-bare-v1` (a body mode filed under underwear) as a garment; they now skip
body modes, as `148e106` did for two others. One was a code defect: `pack.rating_for` read
`plan.template_id` from a plan that need not have it; it now uses `getattr`.

## Tests

`tests/unit/test_body_state_import.py` (27), `tests/integration/test_body_state_api.py` (8),
`tests/unit/test_kept_layers.py` (10), three BI4 cases in `tests/unit/test_dataset_publish.py`.
