"""AN-A5. A garment on her skin moves as her skin does.

Underwear, swimwear, bodysuits, leggings and tights were bound to her pelvis by the fitter's
torso mask, so when her thighs moved the leg openings did not: briefs were 18 mm inside the
median reference body striding and 25 mm standing wide. Such a garment is now bound with her
own skin's weights everywhere (``secondSkin``); dresses and skirts keep their binding, because a
hem across both legs must not be split between them.
"""

from __future__ import annotations

import sys

import pytest

from tests.conftest import job_request
from wardrobe.anatomy import reference as R
from wardrobe.anatomy import regions as G
from wardrobe.anatomy import rig
from wardrobe.anatomy.contact import ContactBody, clearance
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, OutfitRequest
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.providers.templates import TemplateGarmentProvider

sys.path.insert(0, str(R.ROOT / "tools" / "anatomy"))


@pytest.mark.parametrize(
    "prompt, second_skin",
    [
        ("black briefs", True),
        ("black thong", True),
        ("black one-piece swimsuit", True),
        ("black bodysuit", True),
        ("black leggings", True),
        ("sheer black tights", True),
        ("black mini skirt", False),
        ("black bodycon mini dress", False),
        ("grey long cardigan", False),
    ],
)
async def test_second_skin_garments_are_marked(prompt, second_skin):
    catalog = TemplateCatalog.from_directory(R.ROOT / "assets" / "garment_templates")
    plan = plan_outfit(OutfitRequest(prompt=prompt), catalog)
    garment = plan.garments[0]
    artifact = await TemplateGarmentProvider(catalog).create(garment, template=catalog.get(garment.template_id))
    assert bool(artifact.metadata.get("secondSkin")) is second_skin


@pytest.fixture(scope="module")
def reference_body() -> bytes:
    from wardrobe.anatomy.vrm import build_reference_vrm

    return build_reference_vrm("ref-f-median", correctives=False)


async def test_briefs_stay_outside_her_when_she_strides_and_stands_wide(orchestrator, store, reference_body):
    from pelvic_evidence import bind_of, read_skinned

    await store.put("sources/ref.vrm", reference_body)
    payload = job_request("sources/ref.vrm", "black briefs", avatar_id="ref-f-median")
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    data = await store.get(f"looks/{record.look.id}/look.vrm")
    meshes = read_skinned(data)
    body = meshes.pop("BodyMesh")
    (briefs,) = meshes.values()
    bind = bind_of(data)
    V0, T, J, m = R.reference_body("ref-f-median")
    labels = G.region_labels(V0, m.landmarks, J)
    for pose_name in ("stride", "wide"):
        pose = rig.leg_pose(pose_name, J)
        PB = rig.pose_surface(body["V"], bind, pose, weights_of=(body["joints"], body["weights"]))
        PG = rig.pose_surface(briefs["V"], bind, pose, weights_of=(briefs["joints"], briefs["weights"]))
        c = clearance(ContactBody(PB, T, labels=labels, reach=0.04), PG, briefs["T"])
        assert c["penetratingSamples"] == 0 and c["minimumMm"] > 0.0, (pose_name, c)
