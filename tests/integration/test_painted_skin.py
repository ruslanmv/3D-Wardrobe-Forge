"""PB1/PB2. Underwear ends on bare skin or is refused; a fit report says which checks it ran.

AvatarSample B's crop top and shorts are painted into her skin texture. Base Body Prep took
her garment meshes off correctly, and lingerie went on over the painted ones with "fit
passed". Model Girl is the library's one avatar bare under her clothes.

The avatars are declared adult in these jobs' avatar blocks, as an operator's session does;
nothing here is rendered — the assertions are on what the job decided and reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.routes.studio import plan_report
from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.library import AvatarLibrary
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.painted_clothing import painted_skin

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"
SAMPLE_B = LIBRARY / "AvatarSample_B.vrm"
MODEL_GIRL = LIBRARY / "vroid" / "vroid-model-girl.vrm"
LACE_SET = {"prompt": "black lace set", "preset": "italian_lace_brazilian_set"}

pytestmark = pytest.mark.skipif(
    not (SAMPLE_B.exists() and MODEL_GIRL.exists()), reason="the library avatars are fetched by `make library`"
)


async def run(orchestrator, store, path: Path, outfit: dict, **options):
    await store.put("sources/painted.vrm", path.read_bytes())
    payload = job_request("sources/painted.vrm", outfit["prompt"], **options)
    payload["outfit"].update({k: v for k, v in outfit.items() if k != "prompt"})
    # The library's own avatar block (licence terms included), as the library route sends it.
    entry = next(a for a in AvatarLibrary.from_directory(LIBRARY).avatars if a.path == path)
    own = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
    payload["avatar"] = {**own, "storageKey": "sources/painted.vrm", "depictsAdult": True}
    return await orchestrator.run_now(CreateJobRequest.model_validate(payload))


def test_sample_b_has_clothes_painted_on_her_skin_and_model_girl_has_none():
    for path, painted in ((SAMPLE_B, True), (MODEL_GIRL, False)):
        document = GltfDocument.from_bytes(path.read_bytes())
        result = painted_skin(document, measure_body(document, inspect_document(document)), set())
        assert result is not None
        # With nothing on, all of what is painted is in view.
        assert (result.visible_share > 0.3) is painted, (path.name, result.to_dict())


async def test_lingerie_over_painted_clothes_is_refused_not_passed(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_B, LACE_SET, baseBody="replace-outer")
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.PAINTED_CLOTHING_SHOWS
    assert "painted on her skin" in record.error and "Keep her clothes on" in record.error
    # Her garment meshes did come off: the refusal is about her skin, not her clothes.
    assert set(record.fit_report.base_body["removedSlots"]) == {"tops", "bottoms"}
    assert record.fit_report.checks["skin"] == "painted-clothing-shows"
    assert record.fit_report.verdict == "failed"


async def test_lingerie_on_a_bare_body_passes_every_check(orchestrator, store):
    record = await run(orchestrator, store, MODEL_GIRL, LACE_SET, baseBody="replace-outer")
    assert record.state is JobState.COMPLETED, record.error
    checks = record.fit_report.checks
    assert checks["skin"] == "bare" and checks["layerOrder"] == "passed"
    assert checks["bodyPreparation"] == "passed" and checks["structure"] == "passed"
    assert record.fit_report.verdict == "passed"
    look = GltfDocument.from_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    assert {g.slot for g in garment_inventory(look) if g.role == "source"} <= {"shoes"}

async def test_keeping_her_clothes_on_is_styled_not_passed(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_B, LACE_SET, baseBody="preserve")
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.checks["layerOrder"] == "layered"
    assert record.fit_report.verdict == "styled"
    assert record.fit_report.passed  # a valid look, said for what it is


async def test_an_ordinary_outfit_is_not_refused_for_her_painted_skin(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_B, {"prompt": "red bodycon mini dress"})
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.base_body["paintedSkin"]["checked"]


def test_the_plan_warns_before_anyone_waits(template_catalog):
    report = plan_report(SAMPLE_B.read_bytes(), OutfitRequest(**LACE_SET), "replace-outer",
                         template_catalog, depicts_adult=True)
    assert report["paintedSkin"]["underwear"] and report["paintedSkin"]["visibleShare"] > 0.3
    bare = plan_report(MODEL_GIRL.read_bytes(), OutfitRequest(**LACE_SET), "replace-outer",
                       template_catalog, depicts_adult=True)
    assert bare["paintedSkin"]["visibleShare"] <= 0.03
