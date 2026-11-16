# Bare body state: what is built, what a person must supply, and how it is accepted

2026-11-16. Forge `claude/busy-hamilton-m2vq2f`. This is a handoff, not an acceptance report: **no
bare body state of a real character was generated, rendered, inspected or imported in this
work**, and no adult-design review was written. Nothing below changes that; it says what the
software already does, how it was tested, and the smallest set of things an authorized person
must bring for the first dressed → bare → dressed acceptance to be run.

Where each of the eight library characters stands, file by file, is in
`docs/qa/BODY_STATE_CHARACTERS.md`.

## Two results, kept apart

**Engineering.** The route from a reviewed file to a restored character exists and is tested
with fixtures: eligibility (`wardrobe/body_surface/eligibility.py`), the authored-only bare
pipeline (`body-bare-v1`), the operator import and its identity and completeness checks
(`body_state_import.py`), private storage with read grants and account capabilities
(`docs/ACCOUNT_ACCESS.md`), durable withdrawal (`docs/qa/ASSET_WITHDRAWAL.md`), and in the
companion app the wear, verify, cancel, roll back and restore path with its browser drivers.

**Character-specific.** Not done, and not claimed. It needs (1) a properly licensed VRM, (2) a
person's review of that exact file, (3) the bare file made from it, (4) a person's review of
that exact file. None of the eight library characters has a recorded review; this document
makes no statement about whether any of them would or should pass one.

## What stays closed until a person acts

`eligibility.assess` asks five questions for a bare state and reports every answer:

| Question | Owner | State in this repository |
|---|---|---|
| `author-permission` | the VRM's own licence | read from the file, strictly |
| `operator-switch` | the deployment: `WARDROBE_ADULT_BODY_SURFACE` | off by default |
| `adult-declaration` | the operator: `assets/library/policy.json` | declared for all eight (a declaration, not a review) |
| `design-clearance` | **a person who looked at the exact file**: `assets/body_surface/adult-design-reviews.json` | **empty** |
| `private-session` | the job | set by the admin routes |

The import route asks the same five for the source file **and** for the uploaded file. No request
field supplies a review and no code writes the registry. A test review exists only in
`tests/conftest.py: clear_design_for_test`, on the calibration mannequin, in a temporary copy,
with the reviewer named `test-fixture (not a review)`.

## Making the review a job someone can do (RP1)

```bash
# 1. Clothed reference pictures of the exact file, from the app's own renderer (companion repo):
node tools/qa/look-turntable.mjs --vrm <file.vrm> --focus body --out <private dir>/sheets
# 2. The packet: exact SHA-256, the file's own terms, the operator's declaration, rig and
#    expressions, clothing as authored, the five answers as they stand, the pictures by hash,
#    and a BLANK registry entry.
python tools/body_surface/review_packet.py --slug <library slug> --out <private dir>/packet \
    --sheets <private dir>/sheets
python tools/body_surface/review_packet.py --file <candidate.vrm> --out <private dir>/packet   # not in the library
```

The packet records no finding (`tests/unit/test_review_packet.py`: every reviewer field empty,
an entry like that opens nothing, the registry untouched, output refused inside the repository).
The reviewer enters, under `reviews` and the file's SHA-256, `outcome` (`clearly-adult` only if
that is their finding), `reviewer`, `date`, `evidence` (naming the pictures by hash), and commits
it under their own name. Any other finding is not entered and the file stays closed. An edited
file has another hash and no review.

## The asset an authorized creator or operator supplies

Source VRM (the dressed character):

- VRM 0.x or 1.0, a valid humanoid (every required bone), skins, expressions; a face and hair
  skinned to the head; a body mesh that is complete under its clothing (see below).
- Licence terms in the file that permit modification and the intended use, read strictly by
  `wardrobe/policy/license_check.py` and `body_surface/gate.py`; an unknown or missing term is a no.
- In the library with its SHA-256 pinned (`assets/library/models.json`), declared by the
  operator, and **reviewed** as above.

Bare-state VRM made from it (by `body-bare-v1` on a deployment where all five answers are yes,
or by an authorized artist), which `body_state_import.check` accepts only if:

| Requirement | Tolerance / rule | Refusal |
|---|---|---|
| Stated SHA-256 equals the bytes | exact | `sha256-mismatch` |
| Bound to the library's pinned source hash, and not the original bytes | exact | `source-mismatch`, `same-as-original` |
| A VRM of the same spec with a valid humanoid and skins | | `not-a-vrm`, `spec-mismatch`, `rig-invalid` |
| Every humanoid bone on the same node name | position within 1 mm (`RIG_TOLERANCE_M`) | `rig-mismatch` |
| Every expression the source has | by name | `expressions-lost` |
| Same VRM title (or Forge's `"<title> — <look>"`) and authors | exact | `identity-mismatch` |
| Face and hair: every primitive drawn from the active scene, skinned mostly to the head | same vertex and morph counts, positions within 0.1 mm (`IDENTITY_TOLERANCE_M`) | `identity-mismatch`, `identity-unverifiable` |
| No detected clothing remains | Forge tags, Forge markers, VRoid material names | `clothing-remains` |
| Body closed in every band `body-bare-v1` checks | upper, lower, both thighs, both shins | `body-incomplete` |
| Whether surface was rebuilt by Forge | `checks.body-state.reconstructed` is true when a Forge body proxy is in the file | reported, not refused |
| Eligibility, for the source file and for this file | all five answers, both files | `not-permitted` |

`body-bare-v1` removes garments and keeps the body the author made; where that body is not
complete it refuses (`body-incomplete-for-bare`) rather than inventing surface. For a file made
elsewhere the import does **not** compare its body with the source's: whether detail was added
that the author never made is not something this check can tell, and it is one of the things
the review of the output file is for.

## Import, read, withdraw

```bash
# Admin session (the operator). Uploaded bytes only; there is no URL field.
curl -X POST "$FORGE/v1/admin/library/$SLUG/body-states" -H "X-Wardrobe-Admin: $TOKEN" \
  -F file=@bare.vrm -F state=bare -F sourceSha256=$SOURCE_SHA -F sha256=$BARE_SHA \
  -F licence="<terms the operator holds the file under>" -F rightsAttested=true -F name="<name>"
# 201 {look, verdict}; 422 {reason: body_state_*, verdict} with every check's answer.
curl "$FORGE/v1/admin/library/$SLUG/body-states" -H "X-Wardrobe-Admin: $TOKEN"
curl -X DELETE "$FORGE/v1/admin/library/$SLUG/body-states/$LOOK_ID" -H "X-Wardrobe-Admin: $TOKEN"
```

The app never holds the admin token. It reads the private look with an operator read grant on
one device, or a signed-in person's account capability (`docs/ACCOUNT_ACCESS.md`).

## The renderer acceptance, once the asset exists

The companion app's existing driver runs unchanged with the new look id; steps 3 and 4 are
where a bare state is asked for and where the character is dressed again:

```bash
node tools/qa/private-body-state-acceptance.mjs --forge <forge> --grant-file <file> \
    --look-id <import-…> --size desktop --lang en-US --out <private dir>
node tools/qa/private-body-state-acceptance.mjs ... --size phone --lang it-IT
```

Acceptance, per character, desktop and 390 px: the bare state is chosen by the person's words
through `PrivateActionBridge` at the level that opens it; it is downloaded with the grant and
its SHA-256 checked before the loader; the renderer's root is that file; same humanoid bones on
the same nodes, same expressions, same face and hair; dressing again puts her own file back;
a failed download, tampered bytes and a cancelled wear change nothing; no admin header leaves
the page. Screenshots stay in private storage.

## Completion matrix

| Operation | Completed | Exact blocker | Evidence | Next action |
|---|---|---|---|---|
| Original adult VRM validated | **No** for the milestone. File integrity and licence terms of the eight library files are verified by hash and read by `review_packet.py`; none is validated as a clearly adult design | No reviewed file exists | `assets/library/models.json` pins; `review_packet.py` output | Operator chooses or commissions the character and runs the packet |
| Adult-design review present | **No** | `adult-design-reviews.json` is empty; only a person can fill it | The registry; `test_review_packet.py` | A reviewer reviews the exact source file and commits the entry |
| Body-state asset obtained | **No** | Depends on the review; none generated or received here | — | Build with `body-bare-v1` on an eligible deployment, or have it authored to the table above |
| Body mesh verified | **No** for a real character. The checks exist and pass and refuse correctly on fixtures | No asset | `tests/unit/test_body_state_import.py`, `tests/integration/test_bare_body.py` (mannequin: gate tests, not acceptance) | `POST …/body-states` runs them on the real file and reports every answer |
| Rig and expressions preserved | **No** for a bare state. Proven for clothed states of five real characters in the app's renderer | No asset | Companion `docs/qa/WARDROBE_CLOTHED_ACCEPTANCE.md` | Same checks run on import and in the driver |
| Import accepted | **No** for a bare state. Accepted for a lingerie state of AvatarSample A in the earlier run | No asset, and no review of the output file | `docs/qa/BODY_STATE_IMPORT.md` | Review the output file, then import |
| Browser renderer confirmed | **No** for a bare state | No asset | Driver exists: `private-body-state-acceptance.mjs` | Run it with the look id, desktop and phone |
| Original outfit restored | **No** from a bare state. Proven from clothed looks (16 runs) and from the lingerie state (earlier run) | No asset | Same documents | Step 4 of the driver |

## The smallest remaining deliverable

1. One VRM whose licence permits it, chosen by the operator.
2. A person's clearly-adult review of that exact file, in the registry.
3. `WARDROBE_ADULT_BODY_SURFACE=true` on the deployment that will build it.
4. The bare file (built there by `body-bare-v1`, or authored), and a person's review of it.
5. The import, a grant or capability for the app, and the two driver runs.

No code change is needed between step 1 and step 5.
