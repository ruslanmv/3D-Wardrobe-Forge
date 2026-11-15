"""RU1. A look is found by what the planner builds, not by the words that asked for it.

Measured before RU1 on a local Forge: the dictionary outfit "black fitted crop top + blue
straight jeans" took 84 s, and the identical request again took 55 s and made a second look.
"""

from __future__ import annotations

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.pipeline import prebuilt
from wardrobe.pipeline.outfit_dictionary import OUTFITS

TEE = "top-fitted-tee-v1"
OUTFIT = "black fitted crop top + blue straight jeans"


class RecordingQueue:
    def __init__(self):
        self.ids = []

    async def enqueue(self, job_id):
        self.ids.append(job_id)


def _free(prompt: str, **kw) -> CreateJobRequest:
    return CreateJobRequest.model_validate(job_request("sources/test-avatar.vrm", prompt, mode="auto", **kw))


def _template(prompt: str = "black Fitted Tee", **kw) -> CreateJobRequest:
    payload = job_request("sources/test-avatar.vrm", prompt, template_id=TEE, **kw)
    payload["outfit"]["color"] = "black"
    return CreateJobRequest.model_validate(payload)


def test_a_described_outfit_has_a_plan_key_and_no_words_key(template_catalog):
    request = _free(OUTFIT)
    assert prebuilt.cache_key(request, template_catalog) is None
    key = prebuilt.plan_key(request, template_catalog)
    assert key and key.startswith("plan-")
    assert prebuilt.keys_for(request, template_catalog) == [key]


def test_the_words_key_is_still_asked_first_so_the_dataset_still_answers(template_catalog):
    request = _template()
    keys = prebuilt.keys_for(request, template_catalog)
    assert keys[0] == prebuilt.cache_key(request, template_catalog)  # unchanged: every stored key holds
    assert keys[1] == prebuilt.plan_key(request, template_catalog)


def test_rephrasing_the_same_garments_is_the_same_key(template_catalog):
    base = prebuilt.plan_key(_free(OUTFIT), template_catalog)
    for words in ("a black fitted crop top with blue straight jeans", "Black fitted crop top + blue straight-leg jeans"):
        assert prebuilt.plan_key(_free(words), template_catalog) == base, words
    # The same two garments named the other way round are stacked the other way round (the plan's
    # layer order, and its outer fields, follow the words): a different fitting, so not the same look.
    assert prebuilt.plan_key(_free("blue straight jeans + black fitted crop top"), template_catalog) != base


def test_a_different_garment_colour_or_option_is_a_different_key(template_catalog):
    base = prebuilt.plan_key(_free(OUTFIT), template_catalog)
    assert prebuilt.plan_key(_free("red fitted crop top + blue straight jeans"), template_catalog) != base
    assert prebuilt.plan_key(_free("black fitted crop top + blue denim shorts"), template_catalog) != base
    assert prebuilt.plan_key(_free(OUTFIT, private=True), template_catalog) != base
    assert prebuilt.plan_key(_free(OUTFIT, wardrobeId="someone-else"), template_catalog) != base
    other = CreateJobRequest.model_validate(job_request("sources/other.vrm", OUTFIT, mode="auto"))
    assert prebuilt.plan_key(other, template_catalog) != base


def test_body_art_and_unplanned_pieces_have_no_plan_key(template_catalog, monkeypatch):
    assert prebuilt.plan_key(_free(OUTFIT).model_copy(update={"body_art_remove": ["left-forearm"]}),
                             template_catalog) is None
    # A piece of the prompt the planner could not plan: the look made is not the look asked for.
    from wardrobe.pipeline import plan_outfit_stack as stack

    real = stack.plan_outfit_stack

    def with_unplanned(*a, **kw):
        plan = real(*a, **kw)
        return plan.model_copy(update={"unplanned": ["a hood made of spaghetti"]})

    monkeypatch.setattr(stack, "plan_outfit_stack", with_unplanned)
    assert prebuilt.plan_key(_free(OUTFIT), template_catalog) is None


def test_editing_a_template_in_the_outfit_is_a_miss(template_catalog):
    from wardrobe.domain.garments import TemplateCatalog

    request = _free(OUTFIT)
    base = prebuilt.plan_key(request, template_catalog)
    used = {g.template_id for g in __import__(
        "wardrobe.pipeline.plan_outfit_stack", fromlist=["x"]).plan_outfit_stack(request.outfit, template_catalog).garments}
    tid = sorted(used)[0]
    edited = template_catalog.get(tid).model_copy(update={"description": "edited"})
    catalog = TemplateCatalog([*(t for t in template_catalog.all() if t.id != tid), edited])
    assert prebuilt.plan_key(request, catalog) != base


async def test_a_dictionary_outfit_asked_again_is_answered_at_once_and_listed_once(orchestrator, stored_avatar):
    orchestrator.queue = RecordingQueue()
    entry = next(o for o in OUTFITS if o.id == "crop-top-jeans")
    payload = job_request("sources/test-avatar.vrm", entry.prompt, mode="auto")
    payload["outfit"] = entry.request().model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
    request = CreateJobRequest.model_validate(payload)

    first = await orchestrator.run_now(request)
    assert first.state == JobState.COMPLETED
    again = await orchestrator.submit(CreateJobRequest.model_validate(payload))
    assert again.state == JobState.COMPLETED and orchestrator.queue.ids == []
    assert again.look.id == first.look.id
    assert again.events[-1].detail["cache"] == "prebuilt"

    reworded = await orchestrator.submit(_free("a black fitted crop top with blue straight jeans"))
    assert reworded.look.id == first.look.id and orchestrator.queue.ids == []

    listed = await prebuilt.ready_looks(orchestrator.store, "test-avatar", include_private=True)
    mine = [item for item in listed if item.get("plan")]
    assert len(mine) == 1
    assert mine[0]["outfitId"] == "crop-top-jeans"
    assert mine[0]["garments"] and mine[0]["templateId"] is None


async def test_two_described_outfits_are_both_listed(orchestrator, stored_avatar):
    await orchestrator.run_now(_free(OUTFIT))
    await orchestrator.run_now(_free("white fitted tee + black pleated mini skirt"))
    listed = await prebuilt.ready_looks(orchestrator.store, "test-avatar", include_private=True)
    assert len([item for item in listed if item.get("plan")]) == 2


async def test_a_template_look_is_listed_once_as_before(orchestrator, stored_avatar):
    await orchestrator.run_now(_template())
    listed = await prebuilt.ready_looks(orchestrator.store, "test-avatar", include_private=True)
    assert [item["templateId"] for item in listed] == [TEE]
    assert "plan" not in listed[0]


def test_the_prebuild_sends_a_dictionary_outfit_as_the_app_does(template_catalog):
    """The prebuilt look is found only if the prebuild's request keys like the app's."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("prebuild", Path(__file__).parents[2] / "tools" / "prebuild.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    entry = next(o for o in OUTFITS if o.id == "crop-top-jeans")
    sent = entry.request().model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
    body = tool.job_body({"outfit": sent})
    avatar = {"storageKey": "sources/test-avatar.vrm", "avatarId": "test-avatar"}
    prebuilt_request = CreateJobRequest.model_validate({"avatar": avatar, **body})
    # ForgeLibraryClient.createJob + TryOnGenerator: {mode:'auto', prompt}, these three options.
    app_request = CreateJobRequest.model_validate({
        "avatar": avatar,
        "outfit": {"mode": "auto", "prompt": entry.prompt},
        "options": {"renderPreview": True, "engine": "auto", "ensureFoundation": True},
    })
    assert prebuilt.plan_key(prebuilt_request, template_catalog) == prebuilt.plan_key(app_request, template_catalog)
