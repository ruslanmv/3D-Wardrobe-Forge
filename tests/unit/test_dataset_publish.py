"""RU2–RU4. The Space sees the dataset's list, publishes what it makes, and only what can be found."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from wardrobe.pipeline import prebuilt
from wardrobe.storage import dataset_publish as dp

ROOT = Path(__file__).resolve().parents[2]


class FakeHub:
    """A dataset in memory: list, download, commit — the three calls Forge makes."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.commits: list[list[str]] = []
        #: WD1. The paths each commit deleted (empty for a commit that only added).
        self.deleted: list[list[str]] = []
        self.fail_next = False
        #: WD1. Downloads of these paths fail (not "not found": the hub cannot be asked).
        self.unreadable: set[str] = set()
        #: BI4. What the hub answers for visibility: True, False, or None (it cannot be asked).
        self.private = None
        hub = self

        class Api:
            def __init__(self, token=None):
                pass

            def repo_info(self, repo_id, repo_type):
                if hub.private is None:
                    raise RuntimeError("visibility unavailable")
                return types.SimpleNamespace(private=hub.private)

            def list_repo_files(self, repo_id, repo_type):
                return list(hub.files)

            def create_commit(self, repo_id, repo_type, operations, commit_message):
                if hub.fail_next:
                    hub.fail_next = False
                    raise RuntimeError("503 from the hub")
                hub.commits.append([op.path_in_repo for op in operations])
                hub.deleted.append([op.path_in_repo for op in operations if isinstance(op, Delete)])
                for op in operations:
                    if isinstance(op, Delete):
                        hub.files.pop(op.path_in_repo, None)
                        continue
                    src = op.path_or_fileobj
                    hub.files[op.path_in_repo] = Path(src).read_bytes() if isinstance(src, str) else src

        def download(repo_id, filename, repo_type, local_dir, token=None):
            if filename in hub.unreadable:
                raise RuntimeError("502 from the hub")
            if filename not in hub.files:
                raise EntryNotFound(filename)
            target = Path(local_dir) / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(hub.files[filename])
            return str(target)

        class EntryNotFound(Exception):
            pass

        class Add:
            def __init__(self, path_in_repo, path_or_fileobj):
                self.path_in_repo, self.path_or_fileobj = path_in_repo, path_or_fileobj

        class Delete:
            """WD1. A withdrawal's deletions, in the same commit as its list and its receipt."""

            def __init__(self, path_in_repo):
                self.path_in_repo = path_in_repo

        self.module = types.SimpleNamespace(HfApi=Api, hf_hub_download=download, CommitOperationAdd=Add,
                                            CommitOperationDelete=Delete,
                                            utils=types.SimpleNamespace(EntryNotFoundError=EntryNotFound))


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake.module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils", fake.module.utils)
    return fake


def _store(tmp_path, settings, **kw):
    from wardrobe.storage.object_store import HfDatasetObjectStore

    update = {"wardrobe_hf_dataset": "me/looks", **kw}
    return HfDatasetObjectStore(tmp_path / "hf", settings.model_copy(update=update))


def _listed(*looks):
    return json.dumps({"wardrobeId": "mira", "looks": list(looks)}).encode()


def _look(template, colour, look_id, built="2026-11-15T10:00:00"):
    return {"templateId": template, "color": colour, "foundationColor": None, "private": False,
            "lookId": look_id, "vrmUrl": f"/v1/assets/looks/{look_id}/look.vrm", "builtAt": built}


async def test_a_list_written_here_no_longer_hides_the_datasets_newer_one(tmp_path, settings, hub):
    """RU2. Before: the local copy won for the Space's whole life."""
    store = _store(tmp_path, settings, wardrobe_hf_publish=False)
    await store.put(prebuilt.wardrobe_key("mira"), _listed(_look("top-tee", "red", "look_local")))
    hub.files[prebuilt.wardrobe_key("mira")] = _listed(_look("top-tee", "red", "look_local"),
                                                      _look("under-bralette-v1", "black", "look_prebuilt"))
    looks = await prebuilt.ready_looks(store, "mira", include_private=True)
    assert {item["lookId"] for item in looks} == {"look_local", "look_prebuilt"}


def test_merge_keeps_every_look_and_the_newest_of_one_identity():
    old = _look("top-tee", "red", "look_old", "2026-11-01T00:00:00")
    new = _look("top-tee", "red", "look_new", "2026-11-15T00:00:00")
    other = _look("top-tee", "blue", "look_blue")
    merged = prebuilt.merge_lists({"looks": [old, other]}, {"looks": [new]})
    assert {item["lookId"] for item in merged["looks"]} == {"look_new", "look_blue"}
    # Two different outfits of several garments are two looks, not one (RU1's `plan`).
    a = {**_look(None, None, "look_a"), "plan": "plan-a"}
    b = {**_look(None, None, "look_b"), "plan": "plan-b"}
    assert len(prebuilt.merge_lists({"looks": [a]}, {"looks": [b]})["looks"]) == 2


def _finished_look(root: Path, key: str, look_id: str, *, entry=True):
    folder = root / "looks" / look_id
    folder.mkdir(parents=True)
    (folder / "look.vrm").write_bytes(b"vrm")
    (folder / "look.json").write_text("{}")
    if entry:
        (root / "prebuilt").mkdir(exist_ok=True)
        (root / prebuilt.entry_key(key)).write_text(json.dumps({"key": key, "lookId": look_id}))


def test_only_a_look_an_entry_names_is_published(tmp_path, hub):
    """RU4. Before: CI uploaded every looks/<id>/ folder, findable or not."""
    root = tmp_path / "root"
    _finished_look(root, "k1", "look_found")
    _finished_look(root, "k2", "look_orphan", entry=False)
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    sent = hub.commits[0]
    assert "looks/look_found/look.vrm" in sent and "prebuilt/k1.json" in sent
    assert not any("look_orphan" in name for name in sent)
    assert result["looks"] == ["look_found"]


def test_a_list_the_dataset_cannot_be_asked_for_is_held_back(tmp_path, hub, monkeypatch):
    root = tmp_path / "root"
    (root / "prebuilt" / "wardrobes").mkdir(parents=True)
    (root / prebuilt.wardrobe_key("mira")).write_bytes(_listed(_look("top-tee", "red", "look_a")))

    def broken(repo, key):
        raise TimeoutError("hub unreachable")

    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=broken)
    assert result["heldBack"] == [prebuilt.wardrobe_key("mira")]
    assert hub.commits == []  # nothing else to send


def test_orphans_are_the_folders_nothing_names():
    remote = ["looks/look_a/look.vrm", "looks/look_b/look.vrm", "looks/look_c/preview.webp", "prebuilt/x.json"]
    assert dp.orphans(remote, entry_looks=["look_a"], listed_looks=["look_c"]) == ["look_b"]


async def test_the_space_publishes_a_batch_of_looks_it_made(tmp_path, settings, hub):
    """RU3. Before: 'writes stay local — the next prebuild makes it permanent'."""
    store = _store(tmp_path, settings, wardrobe_hf_publish_every=2, wardrobe_hf_publish_seconds=3600)
    for i in (1, 2):
        _finished_look(store.root, f"k{i}", f"look_{i}", entry=False)
        await store.put(prebuilt.entry_key(f"k{i}"), json.dumps({"key": f"k{i}", "lookId": f"look_{i}"}).encode())
    for _ in range(50):  # the batch of two goes up on its own
        if hub.commits:
            break
        await asyncio.sleep(0.02)
    assert len(hub.commits) == 1
    assert {"looks/look_1/look.vrm", "looks/look_2/look.vrm", "prebuilt/k1.json", "prebuilt/k2.json"} <= set(
        hub.commits[0])
    assert store.published["looks"] == 2


async def test_a_failed_commit_is_kept_and_sent_with_the_next(tmp_path, settings, hub):
    store = _store(tmp_path, settings, wardrobe_hf_publish_every=100, wardrobe_hf_publish_seconds=3600)
    _finished_look(store.root, "k1", "look_1", entry=False)
    await store.put(prebuilt.entry_key("k1"), json.dumps({"key": "k1", "lookId": "look_1"}).encode())
    hub.fail_next = True
    assert await store.flush() is None and store.published["failures"] == 1
    await store.close()  # shutdown publishes what is pending
    assert "looks/look_1/look.vrm" in hub.commits[0]


async def test_publishing_off_keeps_writes_local(tmp_path, settings, hub):
    store = _store(tmp_path, settings, wardrobe_hf_publish=False)
    await store.put(prebuilt.entry_key("k1"), b"{}")
    await store.close()
    assert hub.commits == []


def _private_look(root: Path, key: str, look_id: str):
    _finished_look(root, key, look_id)
    (root / "looks" / look_id / "private.json").write_text('{"private": true, "wardrobeId": "mira"}')


def _list_with(root: Path, items: list[dict]):
    (root / "prebuilt" / "wardrobes").mkdir(parents=True, exist_ok=True)
    (root / prebuilt.wardrobe_key("mira")).write_text(json.dumps({"wardrobeId": "mira", "looks": items}))


def test_a_private_look_never_goes_to_a_dataset_not_known_private(tmp_path, hub):
    """BI4. The fake hub has no repo_info: not known private, so nothing private goes up."""
    root = tmp_path / "root"
    _finished_look(root, "k1", "look_public")
    _private_look(root, "k2", "look_secret")
    _list_with(root, [{"lookId": "look_public", "templateId": "t", "private": False},
                      {"lookId": "import-abc", "templateId": None, "plan": "import-abc", "private": True}])
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    sent = hub.commits[0]
    assert "looks/look_public/look.vrm" in sent
    assert not any("look_secret" in name for name in sent) and "prebuilt/k2.json" not in sent
    uploaded = json.loads(hub.files[prebuilt.wardrobe_key("mira")])
    assert [item["lookId"] for item in uploaded["looks"]] == ["look_public"]
    assert result["privateHeldBack"] == ["import-abc", "look_secret"] and result["includePrivate"] is False


def test_a_private_look_goes_to_a_dataset_the_hub_says_is_private(tmp_path, hub):
    root = tmp_path / "root"
    _private_look(root, "k2", "look_secret")
    api = hub.module.HfApi()
    api.repo_info = lambda repo_id, repo_type: types.SimpleNamespace(private=True)
    result = dp.publish(api, "me/looks", root, download=dp.hub_download())
    assert "looks/look_secret/look.vrm" in hub.commits[0] and result["includePrivate"] is True


def test_an_unanswered_visibility_question_counts_as_public(tmp_path, hub):
    api = hub.module.HfApi()

    def boom(**_):
        raise RuntimeError("hub down")

    api.repo_info = boom
    assert dp.dataset_is_private(api, "me/looks") is False


# -- BI4: the privacy boundary is the hub's answer, never a flag ----------------------------------
def _mixed_root(tmp_path) -> Path:
    root = tmp_path / "root"
    _finished_look(root, "k1", "look_public")
    _private_look(root, "k2", "look_secret")
    _list_with(root, [{"lookId": "look_public", "templateId": "t", "private": False},
                      {"lookId": "look_secret", "templateId": "u", "private": True}])
    return root


@pytest.mark.parametrize("visibility", [False, None], ids=["confirmed-public", "unverifiable"])
def test_include_private_cannot_send_private_files_to_a_dataset_not_confirmed_private(tmp_path, hub, visibility):
    hub.private = visibility
    root = _mixed_root(tmp_path)
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download(), include_private=True)
    sent = hub.commits[0]
    assert not any("look_secret" in name for name in sent) and "prebuilt/k2.json" not in sent
    assert "looks/look_public/look.vrm" in sent  # ordinary public looks still go up
    listed = json.loads(hub.files[prebuilt.wardrobe_key("mira")])
    assert [item["lookId"] for item in listed["looks"]] == ["look_public"]
    assert result["refusedPrivate"] is True and result["includePrivate"] is False


def test_a_confirmed_private_dataset_takes_private_looks(tmp_path, hub):
    hub.private = True
    result = dp.publish(hub.module.HfApi(), "me/looks", _mixed_root(tmp_path), download=dp.hub_download())
    assert "looks/look_secret/look.vrm" in hub.commits[0] and result["verifiedPrivate"] is True
    # Asking for less is honoured: False keeps them home even then.
    hub.commits.clear()
    result = dp.publish(hub.module.HfApi(), "me/looks", _mixed_root(tmp_path / "again"),
                        download=dp.hub_download(), include_private=False)
    assert not any("look_secret" in name for name in hub.commits[0]) and result["refusedPrivate"] is False


def test_private_items_already_in_the_dataset_list_are_not_resent_to_a_public_one(tmp_path, hub):
    hub.private = False
    hub.files[prebuilt.wardrobe_key("mira")] = _listed({**_look("u", None, "look_old_secret"), "private": True})
    root = tmp_path / "root"
    _finished_look(root, "k1", "look_public")
    _list_with(root, [{"lookId": "look_public", "templateId": "t", "private": False}])
    dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download(), keep_existing=False)
    listed = json.loads(hub.files[prebuilt.wardrobe_key("mira")])
    assert [item["lookId"] for item in listed["looks"]] == ["look_public"]


def test_the_cli_refuses_include_private_against_a_public_dataset(tmp_path, hub, monkeypatch, capsys):
    import importlib.util

    hub.private = False
    root = _mixed_root(tmp_path)
    spec = importlib.util.spec_from_file_location("publish_prebuilt", ROOT / "tools/publish_prebuilt.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "hub_download", lambda token=None: dp.hub_download())
    code = cli.main(["--root", str(root), "--repo", "me/public-looks", "--include-private"])
    assert code == 3 and "not confirmed private" in capsys.readouterr().err
    assert not any("look_secret" in name for commit in hub.commits for name in commit)


# -- BI5: an imported body state goes up whole, or not at all ------------------------------------
def _import(root: Path, look_id: str, *, files: bool = True) -> dict:
    if files:
        folder = root / "looks" / look_id
        folder.mkdir(parents=True)
        (folder / "look.vrm").write_bytes(b"imported vrm")
        (folder / "private.json").write_text('{"private": true, "wardrobeId": "mira"}')
        (folder / "import.json").write_text(json.dumps({"lookId": look_id}))
    return {"lookId": look_id, "templateId": None, "plan": f"plan-{look_id}", "private": True,
            "origin": "operator-import", "vrmUrl": f"/v1/assets/looks/{look_id}/look.vrm"}


def test_an_import_goes_up_with_its_vrm_marker_and_receipt(tmp_path, hub):
    hub.private = True
    root = tmp_path / "root"
    _list_with(root, [_import(root, "import-aaa")])
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    sent = set(hub.commits[0])
    assert {"looks/import-aaa/look.vrm", "looks/import-aaa/private.json", "looks/import-aaa/import.json",
            prebuilt.wardrobe_key("mira")} <= sent
    assert result["looks"] == ["import-aaa"]


def test_a_list_never_names_an_import_whose_files_cannot_go_up(tmp_path, hub):
    hub.private = True
    root = tmp_path / "root"
    _list_with(root, [_import(root, "import-gone", files=False)])
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    assert json.loads(hub.files[prebuilt.wardrobe_key("mira")])["looks"] == []
    assert result["unavailable"] == ["import-gone"]


async def test_an_import_survives_a_restart_with_no_local_storage(tmp_path, settings, hub):
    """The Space's case: imported, published privately, local disk wiped, a new process reads it back."""
    import shutil

    hub.private = True
    store = _store(tmp_path, settings, wardrobe_hf_publish_every=100, wardrobe_hf_publish_seconds=3600)
    item = await prebuilt.register_import(
        store, "mira", b"imported vrm bytes", verdict={"accepted": True}, state="lingerie", name="Chemise",
        source_sha256="a" * 64, output_sha256="b" * 64, imported_by="admin", provenance={},
        vrm_url="/v1/assets/looks/import-bbbbbbbbbbbbbbbbbbbbbbbb/look.vrm", garments=["under-chemise-satin-v1"])
    hub.fail_next = True
    assert await store.flush() is None  # a failed publication stays pending
    assert await store.flush() is not None
    look = item["lookId"]
    assert {f"looks/{look}/look.vrm", f"looks/{look}/private.json", f"looks/{look}/import.json"} <= set(hub.files)
    await store.close()
    shutil.rmtree(store.root)

    fresh = _store(tmp_path, settings, wardrobe_hf_publish=False)
    listed = await prebuilt.ready_looks(fresh, "mira", include_private=True)
    assert [x["lookId"] for x in listed] == [look] and listed[0]["origin"] == "operator-import"
    assert await fresh.exists(f"looks/{look}/private.json")  # /v1/assets still protects it
    assert await fresh.get(f"looks/{look}/look.vrm") == b"imported vrm bytes"


# -- WD1: a withdrawn import stays withdrawn: across the dataset, a restart, and a stale list ----
LOOK = "import-" + "b" * 24
FILES = [f"looks/{LOOK}/look.vrm", f"looks/{LOOK}/import.json", f"looks/{LOOK}/private.json"]
RECEIPT = f"withdrawn/{LOOK}.json"
MIRA = prebuilt.wardrobe_key("mira")


async def _imported(tmp_path, settings, hub, **kw):
    """An import made on a Space and published to its (private) dataset: the state to withdraw from."""
    hub.private = True
    store = _store(tmp_path, settings, wardrobe_hf_publish_every=100, wardrobe_hf_publish_seconds=3600, **kw)
    await prebuilt.register_import(
        store, "mira", b"imported vrm bytes", verdict={"accepted": True}, state="lingerie", name="Chemise",
        source_sha256="a" * 64, output_sha256="b" * 64, imported_by="admin", provenance={},
        vrm_url=f"/v1/assets/looks/{LOOK}/look.vrm", garments=["under-chemise-satin-v1"])
    if store.publishing:
        assert await store.flush() is not None
        assert set(FILES) <= set(hub.files)
    return store


def _hub_lists(hub) -> list[str]:
    return [item["lookId"] for item in json.loads(hub.files[MIRA])["looks"]]


async def _blocked(store) -> bool:
    """Not listed and not retrievable through this store, whoever asks."""
    from wardrobe.storage import withdrawals

    listed = await prebuilt.ready_looks(store, "mira", include_private=True)
    return not listed and await withdrawals.is_withdrawn(store, LOOK)


async def test_a_withdrawal_deletes_from_the_dataset_in_one_commit(tmp_path, settings, hub):
    """Successful deletion. Before WD1 ``delete`` was local only: the dataset kept the VRM, the
    store said it still existed, and the withdrawal answered "remaining" for ever."""
    store = await _imported(tmp_path, settings, hub)
    commits = len(hub.commits)
    result = await prebuilt.withdraw_import(store, "mira", LOOK, withdrawn_by="ruslan")
    assert result["withdrawn"] and result["remaining"] == [] and not result["repeated"]
    # One commit: the three files deleted, her list rewritten, the receipt added. All or nothing.
    assert len(hub.commits) == commits + 1
    assert sorted(hub.deleted[-1]) == sorted(FILES)
    assert {MIRA, RECEIPT} <= set(hub.commits[-1])
    assert not set(FILES) & set(hub.files) and _hub_lists(hub) == []
    receipt = json.loads(hub.files[RECEIPT])
    assert receipt["state"] == "withdrawn" and receipt["wardrobeId"] == "mira" and receipt["remaining"] == []
    assert receipt["requestedBy"] == "ruslan" and receipt["completedAt"] and receipt["outputSha256"] == "b" * 64
    # Locally too: nothing left, the same receipt, and nothing waiting to be published again.
    for key in FILES:
        assert not await store.exists(key)
    assert json.loads(await store.get(RECEIPT))["state"] == "withdrawn"
    assert await _blocked(store)
    assert await store.flush() is None or not set(FILES) & set(hub.files)


async def test_a_failed_dataset_deletion_is_reported_and_the_look_is_blocked_meanwhile(tmp_path, settings, hub):
    """Failed deletion, then retry. The commit fails: nothing changed in the dataset, the result
    names what remains, and the look is neither listed nor retrievable until the retry finishes."""
    from wardrobe.storage import withdrawals

    store = await _imported(tmp_path, settings, hub)
    hub.fail_next = True
    first = await prebuilt.withdraw_import(store, "mira", LOOK)
    assert first["withdrawn"] is False and sorted(first["remaining"]) == sorted(FILES)
    assert set(FILES) <= set(hub.files) and RECEIPT not in hub.files  # the dataset is untouched
    assert first["receipt"]["state"] == "pending"
    assert json.loads(await store.get(RECEIPT))["state"] == "pending"
    # The dataset still has the VRM and the store could download it again; the receipt blocks it.
    assert await store.exists(FILES[0]) and await _blocked(store)
    # Retry: idempotent, and it finishes.
    second = await prebuilt.withdraw_import(store, "mira", LOOK)
    assert second["withdrawn"] and not set(FILES) & set(hub.files)
    receipt = json.loads(hub.files[RECEIPT])
    assert receipt["state"] == "withdrawn" and receipt["attempts"] == 2
    assert [e["event"] for e in receipt["history"]] == ["requested", "incomplete", "retried", "withdrawn"]
    assert withdrawals.blocks(receipt)


async def test_repeating_a_finished_withdrawal_changes_nothing(tmp_path, settings, hub):
    store = await _imported(tmp_path, settings, hub)
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"]
    commits, before = len(hub.commits), hub.files[RECEIPT]
    again = await prebuilt.withdraw_import(store, "mira", LOOK)
    assert again == {"withdrawn": True, "remaining": [], "receipt": json.loads(before), "repeated": True}
    assert len(hub.commits) == commits and hub.files[RECEIPT] == before
    # Not hers under another avatar; a look that never was is nothing.
    assert await prebuilt.withdraw_import(store, "nora", LOOK) is None
    assert await prebuilt.withdraw_import(store, "mira", "import-" + "c" * 24) is None


async def test_a_publish_between_a_failed_withdrawal_and_its_retry_does_not_restore_the_look(
        tmp_path, settings, hub):
    """Interrupted synchronization. The withdrawal's commit failed; the next ordinary batch then
    published her list. PB7's merge ("a publish never drops a look") used to take the look back
    from the dataset's copy. Now the batch carries the pending receipt up and the list without it."""
    store = await _imported(tmp_path, settings, hub)
    hub.fail_next = True
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"] is False
    result = await store.flush()
    assert result is not None and result["withdrawn"] == [LOOK] and result["receipts"] == [RECEIPT]
    assert _hub_lists(hub) == [] and json.loads(hub.files[RECEIPT])["state"] == "pending"
    # Its files were not sent again (they are still there from before: the retry deletes them).
    assert not [name for name in hub.commits[-1] if name.startswith(f"looks/{LOOK}/")]
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"]
    assert not set(FILES) & set(hub.files)


async def test_a_withdrawn_look_stays_withdrawn_after_a_restart_with_no_local_storage(tmp_path, settings, hub):
    """Restart with fresh local storage, and attempted retrieval after withdrawal."""
    import shutil

    store = await _imported(tmp_path, settings, hub)
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"]
    await store.close()
    shutil.rmtree(store.root)

    fresh = _store(tmp_path, settings)
    assert await _blocked(fresh)
    for key in FILES:
        assert not await fresh.exists(key)
    with pytest.raises(FileNotFoundError):
        await fresh.get(FILES[0])
    receipts = await prebuilt.list_withdrawals(fresh, "mira")
    assert [(r["lookId"], r["state"]) for r in receipts] == [(LOOK, "withdrawn")]
    assert await prebuilt.list_withdrawals(fresh, "nora") == []


async def test_a_restart_finishes_a_withdrawal_that_was_cut_short(tmp_path, settings, hub):
    """Failure recovery. The commit failed, the pending receipt reached the dataset with the next
    batch, then the Space restarted on an empty disk. The dataset still holds the VRM; the new
    process reads the receipt first, blocks the look, and the startup sweep deletes the files."""
    import shutil

    store = await _imported(tmp_path, settings, hub)
    hub.fail_next = True
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"] is False
    await store.close()  # shutdown publishes what is pending: the receipt
    assert json.loads(hub.files[RECEIPT])["state"] == "pending" and set(FILES) <= set(hub.files)
    shutil.rmtree(store.root)

    fresh = _store(tmp_path, settings)
    assert await _blocked(fresh)  # before the sweep: the dataset has the bytes, nobody gets them
    swept = await prebuilt.resume_withdrawals(fresh)
    assert swept == {"resumed": [LOOK], "pending": []}
    assert not set(FILES) & set(hub.files) and json.loads(hub.files[RECEIPT])["state"] == "withdrawn"
    assert await prebuilt.resume_withdrawals(fresh) == {"resumed": [], "pending": []}  # nothing left to do


async def test_a_stale_manifest_and_restored_files_do_not_bring_a_withdrawn_look_back(tmp_path, settings, hub):
    """Protection against restoration from a stale remote manifest. After the withdrawal, the
    dataset's list and the look's files come back (a restored backup, a publisher with an old
    root). The receipt is still there: not listed, not served, and the sweep deletes them again."""
    import shutil

    store = await _imported(tmp_path, settings, hub)
    stale = {key: hub.files[key] for key in [*FILES, MIRA]}
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"]
    await store.close()
    shutil.rmtree(store.root)
    hub.files.update(stale)

    fresh = _store(tmp_path, settings)
    assert _hub_lists(hub) == [LOOK] and await fresh.exists(FILES[0])  # the dataset names and holds it
    assert await _blocked(fresh)
    assert (await prebuilt.resume_withdrawals(fresh))["resumed"] == [LOOK]
    assert not set(FILES) & set(hub.files) and _hub_lists(hub) == []


def test_a_publisher_with_a_stale_root_cannot_republish_a_withdrawn_look(tmp_path, hub):
    """CI's path (tools/publish_prebuilt.py): a root that still lists the import and holds its
    files, against a dataset whose receipt says withdrawn. Neither the files nor the line go up."""
    from wardrobe.storage import withdrawals

    hub.private = True
    root = tmp_path / "root"
    _list_with(root, [_import(root, LOOK)])
    receipt = withdrawals.completed(withdrawals.begin(None, look_id=LOOK, wardrobe_id="mira", files=FILES[:2],
                                                      by="admin"))
    hub.files[RECEIPT] = withdrawals.dumps(receipt)
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    assert result["withdrawn"] == [LOOK] and result["looks"] == []
    assert not [name for commit in hub.commits for name in commit if name.startswith("looks/")]
    assert _hub_lists(hub) == [] and json.loads(hub.files[RECEIPT])["state"] == "withdrawn"


def test_a_list_is_held_back_while_a_receipt_cannot_be_read(tmp_path, hub):
    """Fail closed: whether her import is withdrawn cannot be asked, so her list does not go up."""
    hub.private = True
    root = tmp_path / "root"
    _list_with(root, [_import(root, LOOK)])
    hub.unreadable.add(RECEIPT)
    result = dp.publish(hub.module.HfApi(), "me/looks", root, download=dp.hub_download())
    assert result["heldBack"] == [MIRA] and MIRA not in hub.files


async def test_importing_the_same_file_again_is_what_lifts_a_receipt(tmp_path, settings, hub):
    """The operator's own act, never a merge's. The receipt stays, as history."""
    store = await _imported(tmp_path, settings, hub)
    assert (await prebuilt.withdraw_import(store, "mira", LOOK))["withdrawn"]
    await _imported(tmp_path, settings, hub)  # the same bytes, the same look id, imported again
    receipt = json.loads(hub.files[RECEIPT])
    assert receipt["state"] == "restored" and [e["event"] for e in receipt["history"]][-2:] == [
        "withdrawn", "restored"]
    assert set(FILES) <= set(hub.files) and _hub_lists(hub) == [LOOK]
    listed = await prebuilt.ready_looks(_store(tmp_path, settings), "mira", include_private=True)
    assert [item["lookId"] for item in listed] == [LOOK]
    # And it can be withdrawn again: a new request on the same record.
    again = await prebuilt.withdraw_import(_store(tmp_path, settings), "mira", LOOK)
    assert again["withdrawn"] and again["receipt"]["attempts"] == 1
    assert [e["event"] for e in again["receipt"]["history"]] == [
        "requested", "withdrawn", "restored", "requested", "withdrawn"]


async def test_a_dataset_this_forge_cannot_write_reports_its_copies_as_remaining(tmp_path, settings, hub):
    """``wardrobe_hf_publish`` off: the dataset's files cannot be deleted from here. Said, not
    hidden: the withdrawal is incomplete, and the look is blocked for as long as this disk lives."""
    writer = await _imported(tmp_path, settings, hub)
    await writer.close()
    reader = _store(tmp_path, settings, wardrobe_hf_publish=False)
    result = await prebuilt.withdraw_import(reader, "mira", LOOK)
    assert result["withdrawn"] is False and sorted(result["remaining"]) == sorted(FILES)
    assert set(FILES) <= set(hub.files) and await _blocked(reader)


async def test_purge_deletes_the_guard_only_when_what_it_guards_is_gone(tmp_path, settings, monkeypatch):
    """The base rule, on plain local storage: the marker outlives a file that will not delete."""
    from wardrobe.storage.object_store import LocalObjectStore

    store = LocalObjectStore(tmp_path / "local", settings)
    for key in FILES:
        await store.put(key, b"x")
    real = LocalObjectStore.delete

    async def failing(self, key):
        if key.endswith("/look.vrm"):
            raise OSError("disk says no")
        return await real(self, key)

    monkeypatch.setattr(LocalObjectStore, "delete", failing)
    left = await store.purge(FILES[:2], then=[FILES[2]], replace={RECEIPT: b"{}"})
    assert left == [FILES[0]] and await store.exists(FILES[2]) and not await store.exists(RECEIPT)
    monkeypatch.setattr(LocalObjectStore, "delete", real)
    assert await store.purge(FILES[:2], then=[FILES[2]], replace={RECEIPT: b"{}"}) == []
    assert not await store.exists(FILES[2]) and await store.exists(RECEIPT)
    assert await store.list_keys("withdrawn") == [RECEIPT]
    assert await store.purge(FILES[:2], then=[FILES[2]], replace={RECEIPT: b"{}"}) == []  # safe to repeat
