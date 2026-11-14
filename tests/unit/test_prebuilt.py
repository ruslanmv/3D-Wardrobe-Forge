"""PB1. A catalog look made once is answered from storage, and only an identical request gets it."""

from __future__ import annotations

from tests.conftest import job_request
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.pipeline import prebuilt
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository

TEE = "top-fitted-tee-v1"


class RecordingQueue:
    """A queue that keeps what was enqueued: a miss is queued, a hit never is."""

    def __init__(self):
        self.ids = []

    async def enqueue(self, job_id):
        self.ids.append(job_id)


def _request(**kw) -> CreateJobRequest:
    return CreateJobRequest.model_validate(job_request("sources/test-avatar.vrm", kw.pop("prompt", "a tee"),
                                                      template_id=kw.pop("template_id", TEE), **kw))


def test_only_a_catalog_request_has_a_key(template_catalog):
    assert prebuilt.cache_key(_request(), template_catalog)
    free = _request(mode="auto", template_id=None)
    assert prebuilt.cache_key(free, template_catalog) is None
    tattooed = _request().model_copy(update={"body_art_remove": ["left-forearm"]})
    assert prebuilt.cache_key(tattooed, template_catalog) is None
    assert prebuilt.cache_key(_request(template_id="no-such-template"), template_catalog) is None


def test_the_key_keeps_everything_that_shapes_the_look(template_catalog, monkeypatch):
    base = prebuilt.cache_key(_request(), template_catalog)
    assert prebuilt.cache_key(_request(), template_catalog) == base
    # The words can carry the colour ("red tee"): without one the planner falls back to grey.
    assert prebuilt.cache_key(_request(prompt="a red tee"), template_catalog) != base
    assert prebuilt.cache_key(_request(private=True), template_catalog) != base
    assert prebuilt.cache_key(_request(wardrobeId="someone-else"), template_catalog) != base
    red = _request()
    red.outfit.color = "red"
    red_key = prebuilt.cache_key(red, template_catalog)
    assert red_key != base
    monkeypatch.setitem(prebuilt.COLORS, "red", "#ff0000")  # a retuned colour is a different look
    assert prebuilt.cache_key(red, template_catalog) != red_key


def test_editing_a_template_or_the_pipeline_is_a_miss(template_catalog, monkeypatch):
    base = prebuilt.cache_key(_request(), template_catalog)
    edited = template_catalog.get(TEE).model_copy(update={"description": "edited"})
    catalog = TemplateCatalog([*(t for t in template_catalog.all() if t.id != TEE), edited])
    assert prebuilt.cache_key(_request(), catalog) != base
    monkeypatch.setattr(prebuilt, "PIPELINE_VERSION", prebuilt.PIPELINE_VERSION + 1)
    assert prebuilt.cache_key(_request(), template_catalog) != base


async def test_a_second_identical_request_is_answered_at_once(orchestrator, stored_avatar):
    orchestrator.queue = RecordingQueue()
    first = await orchestrator.run_now(_request())
    assert first.state == JobState.COMPLETED

    again = await orchestrator.submit(_request())
    assert again.state == JobState.COMPLETED
    assert orchestrator.queue.ids == []
    assert again.id != first.id
    assert again.look.id == first.look.id
    assert again.events[-1].detail["cache"] == "prebuilt"
    assert (await orchestrator.get(again.id)).look.id == first.look.id

    other = await orchestrator.submit(_request(template_id="top-camisole-v1"))
    assert other.state == JobState.QUEUED
    assert orchestrator.queue.ids == [other.id]


async def test_a_broken_entry_or_a_lost_look_is_a_miss(orchestrator, store, stored_avatar):
    orchestrator.queue = RecordingQueue()
    first = await orchestrator.run_now(_request())
    key = prebuilt.cache_key(_request(), orchestrator.catalog)

    await store.delete(f"looks/{first.look.id}/look.vrm")
    assert (await orchestrator.submit(_request())).state == JobState.QUEUED

    await store.put(prebuilt.entry_key(key), b"not json")
    assert (await orchestrator.submit(_request())).state == JobState.QUEUED


async def test_the_switch_turns_it_off(settings, store, template_catalog, stored_avatar):
    off = settings.model_copy(update={"wardrobe_prebuilt": False})
    orch = Orchestrator(settings=off, store=store, jobs=InMemoryJobRepository(),
                        wardrobes=InMemoryWardrobeRepository(), queue=RecordingQueue(),
                        catalog=template_catalog)
    await orch.run_now(_request())
    assert (await orch.submit(_request())).state == JobState.QUEUED
    assert not await store.exists(prebuilt.entry_key(prebuilt.cache_key(_request(), template_catalog)))


async def test_the_dataset_store_reads_through_once_and_writes_locally(tmp_path, monkeypatch, settings):
    import sys
    import types

    from wardrobe.storage.object_store import HfDatasetObjectStore

    remote = {"looks/look_a/look.vrm": b"vrm-bytes"}
    calls = {"list": 0, "download": 0}

    class FakeApi:
        def list_repo_files(self, repo_id, repo_type):
            calls["list"] += 1
            assert (repo_id, repo_type) == ("me/looks", "dataset")
            return list(remote)

    def fake_download(repo_id, filename, repo_type, local_dir):
        calls["download"] += 1
        target = tmp_path / "hf" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(remote[filename])

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(HfApi=FakeApi, hf_hub_download=fake_download))
    store = HfDatasetObjectStore(tmp_path / "hf", settings.model_copy(update={"wardrobe_hf_dataset": "me/looks"}))

    assert await store.exists("looks/look_a/look.vrm")
    assert not await store.exists("looks/look_b/look.vrm")
    assert await store.get("looks/look_a/look.vrm") == b"vrm-bytes"
    assert await store.get("looks/look_a/look.vrm") == b"vrm-bytes"
    assert calls == {"list": 1, "download": 1}  # listed once, downloaded once, then local

    await store.put("looks/look_c/look.vrm", b"made here")
    assert await store.get("looks/look_c/look.vrm") == b"made here"
    assert "looks/look_c/look.vrm" not in remote  # never written back to the dataset


async def test_simultaneous_writes_of_one_key_never_fail(store):
    import asyncio

    payloads = [f"version {i}".encode() for i in range(20)]
    await asyncio.gather(*(store.put("wardrobes/mira/wardrobe.json", p) for p in payloads))
    assert await store.get("wardrobes/mira/wardrobe.json") in payloads
    leftovers = list((store.root / "wardrobes" / "mira").glob("*.part"))
    assert leftovers == []


async def test_two_looks_finishing_together_are_both_in_her_wardrobe(orchestrator, stored_avatar):
    import asyncio

    tee, cami = await asyncio.gather(
        orchestrator.run_now(_request()), orchestrator.run_now(_request(template_id="top-camisole-v1"))
    )
    manifest = await orchestrator.wardrobes.get("test-avatar")
    ids = {look.id for look in manifest.looks}
    assert tee.look.id in ids and cami.look.id in ids
