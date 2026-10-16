"""PB1/PB2, SR1, BC1. Underwear ends on her skin; a fit report says which checks it ran.

AvatarSample B's crop top and shorts are painted into her skin texture; lingerie went on
over them with "fit passed", then (PB1) was refused. Her skin is now restored under the
underwear (SR1). AvatarSample_O's export deleted her chest under her top; the job was
refused, and her body is now completed there (BC1). Model Girl is bare under her clothes
and is left exactly as she is.

The avatars are declared adult in these jobs' avatar blocks, as an operator's session does;
nothing here is rendered — the assertions are on what the job decided and reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.routes.studio import plan_report
from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.library import AvatarLibrary
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.painted_clothing import painted_skin

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"
SAMPLE_B = LIBRARY / "AvatarSample_B.vrm"
SAMPLE_O = LIBRARY / "vroid" / "vroid-avatar-sample-o.vrm"
MODEL_GIRL = LIBRARY / "vroid" / "vroid-model-girl.vrm"
LACE_SET = {"prompt": "black lace set", "preset": "italian_lace_brazilian_set"}

pytestmark = pytest.mark.skipif(
    not (SAMPLE_B.exists() and MODEL_GIRL.exists() and SAMPLE_O.exists()), reason="the library avatars are fetched by `make library`"
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


async def test_lingerie_over_painted_clothes_restores_her_skin(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_B, LACE_SET, baseBody="replace-outer")
    assert record.state is JobState.COMPLETED, record.error
    body = record.fit_report.base_body
    assert set(body["removedSlots"]) == {"tops", "bottoms"}
    assert body["skinRestored"]["restoredTexels"] > 100_000  # the crop top and the shorts
    assert body["paintedSkin"]["visibleShare"] < 0.01
    assert record.fit_report.checks["skin"] == "restored" and record.fit_report.verdict == "passed"
    # Her own file is untouched; the look carries new textures, the old ones are not changed.
    look = GltfDocument.from_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    skin = next(m for m in look.gltf["materials"] if m["name"] == "F00_000_00_Body_00_SKIN")
    assert skin["pbrMetallicRoughness"]["baseColorTexture"]["index"] in body["skinRestored"]["textures"].values()


async def test_a_body_her_export_deleted_is_completed(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_O, LACE_SET, baseBody="replace-outer")
    assert record.state is JobState.COMPLETED, record.error
    body = record.fit_report.base_body
    assert body["bodyCompleted"]["holeCells"] > 0 and "tops" in body["removedSlots"]
    assert body["complete"] is True and record.fit_report.verdict == "passed"


async def test_an_ordinary_outfit_never_touches_her_skin(orchestrator, store):
    record = await run(orchestrator, store, SAMPLE_B, {"prompt": "red bodycon mini dress"})
    assert record.state is JobState.COMPLETED, record.error
    assert "skinRestored" not in record.fit_report.base_body
    assert record.fit_report.base_body["paintedSkin"]["checked"]


async def test_a_plunge_restores_her_skin_where_it_opens(orchestrator, store):
    """AN1. An outer garment cut to show skin her clothes hid: the plunge opened onto paint."""
    record = await run(orchestrator, store, SAMPLE_B, {"prompt": "black latex catsuit with plunging neckline"})
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.base_body["skinRestored"]["restoredTexels"] > 0
    assert any("open cut" in w for w in record.fit_report.warnings)


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
    assert "skinRestored" not in record.fit_report.base_body  # her clothes stay: so does her skin


def test_the_plan_warns_before_anyone_waits(template_catalog):
    report = plan_report(SAMPLE_B.read_bytes(), OutfitRequest(**LACE_SET), "replace-outer",
                         template_catalog, depicts_adult=True)
    assert report["paintedSkin"]["underwear"] and report["paintedSkin"]["visibleShare"] > 0.3
    hole = plan_report(SAMPLE_O.read_bytes(), OutfitRequest(**LACE_SET), "replace-outer",
                       template_catalog, depicts_adult=True)
    assert hole["bodyCompletion"] == ["upper"]
    bare = plan_report(MODEL_GIRL.read_bytes(), OutfitRequest(**LACE_SET), "replace-outer",
                       template_catalog, depicts_adult=True)
    assert bare["paintedSkin"]["visibleShare"] <= 0.03
