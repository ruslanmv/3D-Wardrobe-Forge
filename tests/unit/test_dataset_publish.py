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


class FakeHub:
    """A dataset in memory: list, download, commit — the three calls Forge makes."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.commits: list[list[str]] = []
        self.fail_next = False
        hub = self

        class Api:
            def list_repo_files(self, repo_id, repo_type):
                return list(hub.files)

            def create_commit(self, repo_id, repo_type, operations, commit_message):
                if hub.fail_next:
                    hub.fail_next = False
                    raise RuntimeError("503 from the hub")
                hub.commits.append([op.path_in_repo for op in operations])
                for op in operations:
                    src = op.path_or_fileobj
                    hub.files[op.path_in_repo] = Path(src).read_bytes() if isinstance(src, str) else src

        def download(repo_id, filename, repo_type, local_dir, token=None):
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

        self.module = types.SimpleNamespace(HfApi=Api, hf_hub_download=download, CommitOperationAdd=Add,
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
