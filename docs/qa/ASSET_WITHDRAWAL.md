# Durable withdrawal of an imported asset (WD1)

2026-11-16. Forge `claude/busy-hamilton-m2vq2f` on `ultimate` @ `fd5eb08`.

## What was wrong

`DELETE /v1/admin/library/{slug}/body-states/{lookId}` deleted the import's list line, its files
and its private marker. Deleting is an absence, and three things fill absences:

| Where | What happened to a withdrawn import |
|---|---|
| `HfDatasetObjectStore.delete` | Removed the local copy only. `exists` answered from the dataset's listing and `get` downloaded the file again: on a Space the withdrawal answered 503 "remaining" for ever, and the look was served the whole time. |
| A restart on an empty disk | `prebuilt.read_list` merges the local list with the dataset's (RU2). The local list was gone, the dataset's still named the look: it was back in her wardrobe, its VRM one download away. |
| `dataset_publish.publish` | Merges the local list with the dataset's so a publish never drops a look (PB7). A withdrawn look is a look the local list dropped: the next batch restored its line. A publisher whose root still held the files sent those again too. |

## What it is now

A **withdrawal receipt**, `withdrawn/<lookId>.json` (`wardrobe/storage/withdrawals.py`), written
before anything is deleted and never deleted itself. While its state is `pending` or `withdrawn`:

- `prebuilt.read_list` does not list the look, from whichever copy of the list names it;
- `/v1/assets/looks/<lookId>/…` serves it to no one (admin session and read grant included);
- `dataset_publish.publish` neither sends its files nor merges its line back, and holds a list
  back when a receipt it needs cannot be read (fail closed).

The sequence (`prebuilt.withdraw_import`), each step safe to repeat and to resume:

1. Receipt, state `pending` (who asked, when, the files to delete, attempt number).
2. Her list rewritten without the look.
3. `store.purge(files, then=[marker], replace={receipt: final}, unlist={list: lookId})`:
   `look.vrm` and `import.json` deleted and **confirmed** gone, then the private marker (never
   while a file it protects remains). On the dataset store the dataset's copies are deleted, its
   own list is rewritten without the look, and the final receipt is added in **one commit**
   (`dataset_publish.withdraw_commit`): all of it or none of it.
4. Receipt, state `withdrawn`, written only when nothing remains.

A failure anywhere leaves a `pending` receipt and the look blocked. It is finished by repeating
the `DELETE` (idempotent), or by the next start (`prebuilt.resume_withdrawals`, called from the
app's lifespan before anything is served). The same sweep deletes the files of a `withdrawn`
look again if they have reappeared in the store.

Only the operator importing the same bytes again lifts a receipt: its state becomes `restored`
and its history is kept. No merge, publish or restart can do that.

## HTTP

| Call | Answer |
|---|---|
| `DELETE /v1/admin/library/{slug}/body-states/{lookId}` | `204` withdrawn, also when it already was. `503 {reason: body_state_withdraw_incomplete, remaining}`: blocked, some files remain, repeat. `404`: no such import for her, never withdrawn. |
| `GET /v1/admin/library/{slug}/withdrawals` | `{slug, count, withdrawals: [receipt…]}`, admin session only. |
| `GET /v1/assets/withdrawn/…` | `404` without an admin session: a receipt is not an asset. |

Receipt fields: `lookId`, `wardrobeId`, `state`, `outputSha256`, `sourceSha256`, `name`,
`wardrobeState`, `files`, `remaining`, `requestedAt`, `requestedBy`, `completedAt`, `attempts`,
`updatedAt`, `history[] {at, event, …}` with events `requested`, `incomplete`, `retried`,
`withdrawn`, `restored`.

Two answers changed on purpose (both in `test_body_state_api`): during an incomplete withdrawal
the admin session no longer gets the file (was 200), and repeating a finished withdrawal answers
204 (was 404).

## Tests (no credentials, the dataset in memory)

`tests/unit/test_dataset_publish.py` uses the existing `FakeHub` fixture, extended with deletions
(`CommitOperationDelete`) and unreadable downloads; `tests/integration/test_withdrawal_api.py`
drives the HTTP API on `HfDatasetObjectStore` over the same fixture.

| Case | Test |
|---|---|
| Successful deletion, one commit | `test_a_withdrawal_deletes_from_the_dataset_in_one_commit` |
| Failed deletion, then retry | `test_a_failed_dataset_deletion_is_reported_and_the_look_is_blocked_meanwhile` |
| Interrupted synchronization | `test_a_publish_between_a_failed_withdrawal_and_its_retry_does_not_restore_the_look` |
| Restart with fresh local storage | `test_a_withdrawn_look_stays_withdrawn_after_a_restart_with_no_local_storage` |
| Failure recovery at startup | `test_a_restart_finishes_a_withdrawal_that_was_cut_short` |
| Stale remote manifest, restored files | `test_a_stale_manifest_and_restored_files_do_not_bring_a_withdrawn_look_back` |
| A stale publisher (CI's path) | `test_a_publisher_with_a_stale_root_cannot_republish_a_withdrawn_look` |
| Receipt unreadable: fail closed | `test_a_list_is_held_back_while_a_receipt_cannot_be_read` |
| Repeated withdrawal | `test_repeating_a_finished_withdrawal_changes_nothing` |
| Re-import lifts the receipt | `test_importing_the_same_file_again_is_what_lifts_a_receipt` |
| Read-only dataset | `test_a_dataset_this_forge_cannot_write_reports_its_copies_as_remaining` |
| Marker last (local store) | `test_purge_deletes_the_guard_only_when_what_it_guards_is_gone`, `test_a_failed_vrm_deletion_keeps_the_marker_and_a_retry_finishes` |
| Attempted retrieval, over HTTP, across restarts | `test_withdrawal_api.py` (first two tests) |

### Found in review of WD1, and fixed

Two defects, each reproduced by a failing test before the fix (16 new tests failed on the
unfixed code across these two and the revocation fix in `docs/ACCOUNT_ACCESS.md`).

**A local receipt hid the dataset's.** `withdrawals.read` asked the store with `get`, and the
dataset store answers `get` from its own disk whenever it has the file. A Forge that had once
downloaded a receipt as `restored` never saw another Forge withdraw the look again: it kept
listing it and serving the VRM from its disk for as long as that disk lived. Now `read` takes
this store's copy **and** the shared one (`ObjectStore.read_shared`) and the one written last
decides. The shared copy is the dataset's as it was at most `LIST_TTL_S` (10 minutes) ago, or
it is "cannot tell": when the dataset cannot be listed, or the receipt cannot be downloaded,
`read_shared` raises and the import is served to no one (a remembered answer is not used; a
failure is remembered for `RETRY_S`, 30 s, so an outage costs one request per receipt per half
minute). Only an operator import can be withdrawn (`can_be_withdrawn`), so no other look is
refused for this reason or costs a lookup.

**An unreadable receipt held back the list but not the files.** `publish` held back a wardrobe
list naming an import whose dataset receipt could not be downloaded, and still uploaded that
import's folder: a root that still held a withdrawn import's files put the deleted VRM back.
Now neither goes up (`receiptUnreadable` in the result) and both wait for a publish that can
ask; then a withdrawn or pending or unparseable receipt blocks, and an import that was never
withdrawn goes up whole.

| Case | Test |
|---|---|
| Another Forge's withdrawal reaches a reader holding a `restored` receipt and a cached VRM | `test_another_forges_withdrawal_reaches_a_reader_holding_a_restored_receipt` |
| The same over HTTP, a running Forge and then its restart on the stale disk | `test_another_forges_withdrawal_stops_a_running_forge_serving_its_cached_copy` |
| A reading is never older than the listing; the hub down means refused | `test_a_reading_of_the_shared_receipt_is_never_older_than_the_listing`, `test_a_forge_that_cannot_reach_the_dataset_serves_no_import_it_cannot_vouch_for` |
| Shared receipt cannot be downloaded | `test_a_shared_receipt_that_cannot_be_read_blocks_the_look` |
| Files and list both held back; retry sends an import that was never withdrawn | `test_an_imports_files_are_held_back_with_its_list_while_its_receipt_cannot_be_read` |
| Retry when the receipt says withdrawn / pending / is not a receipt | `test_after_the_error_passes_a_withdrawn_import_still_does_not_go_up` (3 cases) |
| The Space's own batch | `test_the_space_itself_holds_an_import_back_while_its_receipt_cannot_be_read` |

## Limits, stated

- **Not verified against the real Hugging Face hub.** The commit uses `CommitOperationDelete` and
  `CommitOperationAdd` in one `create_commit`, which the hub applies atomically; that was run
  against the in-memory fixture only. Verifying on the deployed dataset needs `HF_TOKEN` and is
  outstanding.
- **Another running Forge on the same dataset** learns of a withdrawal when its view of the
  dataset refreshes: at most `LIST_TTL_S` (10 minutes) later. That window is the freshness
  guarantee, and it is not zero: for up to ten minutes after one Forge withdraws a look, another
  that was already serving it may still do so. After that it serves it to no one, whether or
  not it can reach the dataset. It keeps the bytes it had downloaded on its own disk, unserved,
  until its next start's sweep. A shorter window is a smaller `LIST_TTL_S` (one listing request
  per window); an immediate one would need the Forges to notify each other, which they do not.
- **A Forge that cannot reach the dataset serves no imported body state** once its last view is
  older than `LIST_TTL_S`. That is the price of the rule above; every other look is unaffected.
- **Receipts are compared by their `updatedAt`**, written by each Forge's own clock. Two Forges
  whose clocks disagree by more than the time between a restore and a withdrawal could order
  them wrongly; a tie goes to the blocking receipt.
- **A withdrawal that never reached the dataset and whose disk was then lost** is lost: there
  was nowhere durable to record it. The operator was answered 503, not 204.
- **A dataset this Forge cannot write** (`WARDROBE_HF_PUBLISH=false`): its copies are reported as
  remaining; the look is blocked by the local receipt only.
- **S3**: `purge` deletes and confirms each object; there is no multi-object transaction, so the
  receipt (written first) is what makes an interrupted withdrawal resumable. Not run against a
  real bucket.
- **Dataset history.** A deleted file remains in the dataset repository's git history until the
  history is rewritten (`super_squash_history` or a fresh repository). Withdrawal makes the file
  unlisted and unserved by Forge; erasing history is an operator action on the hub.
