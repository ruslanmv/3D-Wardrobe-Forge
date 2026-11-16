# Intake checklist: a character that is adult by design (Track B)

2026-11-16. For the case where none of the library characters is reviewed `clearly-adult`, or
where the operator decides not to put them forward. This is the checklist an operator fills in
**before** a file is pinned in the library; once it is pinned, the file starts at Phase 0 of
`docs/qa/BARE_STATE_HANDOFF.md` like any other. Nothing here is a review, and nothing here
opens anything: the five eligibility answers stay where they are until the people named below
act.

Why this exists. The eight library characters are stylised anime avatars made as general-purpose
samples. None was designed with an age, and a character not designed as an adult cannot be made
one by a declaration, a licence or a review that wants it to pass. A bare state needs a character
whose adulthood is a fact of its design, visible to a reviewer who has only the file and its
clothed pictures. This sheet is how such a file comes in.

## 1. What the operator supplies (nothing is pinned without all of it)

| # | Item | Who | How it is checked | A "no" means |
|---|---|---|---|---|
| 1 | The VRM file itself, as bytes (no URL) | operator | `sha256sum`; the hash is what everything else is keyed on | — |
| 2 | The creator's brief stating the character is an adult, with an age or life stage the design shows (build, proportions, face) | creator, via operator | read by the reviewer in Phase 0; kept beside the file in `assets/library/` provenance | not this file |
| 3 | A written licence from the creator permitting **modification**, **redistribution to the operator's deployment**, and **sexual expression** | creator, via operator | read by the operator; recorded as provenance where the file lands (`assets/library/`) | not this file |
| 4 | The same terms **in the file's own meta**. VRM 1.0: `meta.modification` allowing modification, `meta.allowExcessivelySexualUsage: true`. VRM 0.x: `meta.sexualUssageName: "Allow"` and a licence that states modification (a VRM 0.x "Other" licence with no URL reads as *unknown*, which is a no) | creator | `wardrobe/policy/licensing.py` (modification) and `wardrobe/policy/intimate.py: sexual_usage_disallowed` (sexual usage), read strictly by `eligibility.assess` → `author-permission` | not this file; the file's own terms cannot be overridden |
| 5 | Clothing as **separate meshes** over a body that is **complete under them**: not painted on the skin, not deleted under the clothes, not cut away by alpha | creator | `asset_spec.py --preflight` and `body-bare-v1`'s band check (upper, lower, both thighs, both shins); `tools/audit/bare_readiness.py` | `body-incomplete-for-bare`; the refusal stands, nothing is reconstructed |
| 6 | A valid humanoid (every required bone, fingers included), expressions, face and hair skinned to the head, under 64 MB; VRM 1.0 preferred | creator | `review_packet.py` (identity section), `asset_spec.py` | fix in the source, new file, new hash |
| 7 | Apache-2.0-compatible provenance for redistribution in this project (the companion app's licence) | operator | recorded beside the file | not in the companion app's `vendor/` |

## 2. What the operator does, in order

1. Puts the file somewhere private, outside both working trees, and records its SHA-256.
2. Adds it to `assets/library/models.json` **pinned by that SHA-256**, with the licence record
   from item 3. (An agent may make this commit once items 1–7 are in hand; it changes no answer.)
3. Declares it in `assets/library/policy.json`. That is the operator's declaration
   (`adult-declaration`), and only the operator makes it.
4. Writes its working sheet: `python tools/body_surface/asset_spec.py --slug <slug> --out docs/qa/body-state-specs`.
5. Phase 0: clothed pictures and the packet, both private:

   ```bash
   # companion app
   node tools/qa/look-turntable.mjs --vrm <file.vrm> --focus body --out <private>/sheets
   # Forge
   python tools/body_surface/review_packet.py --slug <slug> --out <private>/packet --sheets <private>/sheets
   ```

   `look-turntable.mjs` measures which way she faces and records it per row in
   `turntable.json` (`facing`), so "front" is her front for VRM 0.x and 1.0 alike.

6. Hands the packet to a reviewer. The reviewer, and only the reviewer, writes the entry in
   `assets/body_surface/adult-design-reviews.json` under the file's SHA-256 and commits it under
   their own name. Any finding other than `clearly-adult` is not entered.

From there the file follows Phases 1 to 3 of the handoff unchanged: build into a private
directory with `WARDROBE_ADULT_BODY_SURFACE=true` on the local command only, packet of the
output with blank fields, a second review of the output's SHA-256, import, grant, driver.

## 3. Stop conditions

- The creator's brief does not state the character is an adult, or the design does not show it
  to someone who has only the clothed pictures: stop. Not a reviewer's borderline call to make.
- The file's own meta forbids sexual usage or modification, or does not state modification:
  stop. A side letter does not override the file; ask the creator for a corrected file.
- The body is incomplete under the clothing: stop. Commission a complete body (the
  AvatarSample_O specification in `docs/qa/BODY_STATE_CHARACTERS.md` is the template), which is
  a new file with its own hash and its own review.
- Anyone, a person or an agent, finds the character reads as a minor or age-ambiguous: stop for
  that file, whatever the registry or declaration says.
