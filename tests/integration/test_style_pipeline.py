"""Finish, see-through fabric, pattern and coverage, end to end.

The acceptance bar for the style layer: each look plans correctly, builds valid
geometry, re-imports as a valid VRM with its humanoid rig intact, passes the
fit checks — and keeps the material behaviour it asked for, in the file, under
the avatar's own toon shader. A look that "succeeds" as flat opaque colour is
the failure this layer exists to prevent, so the material is asserted too.
"""

from __future__ import annotations

import pytest

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument


@pytest.fixture(scope="module")
def toon_avatar() -> bytes:
    """The VRM 1.0 calibration body — its terms allow what the VRM 0.x one does not — in MToon clothes."""
    return dress_like_vroid(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"), mtoon=True)


async def dress(orchestrator, store, source: bytes, prompt: str, *, adult: bool = True):
    await store.put("sources/style.vrm", source)
    payload = job_request("sources/style.vrm", prompt)
    payload["avatar"]["depictsAdult"] = adult
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output


def garment_material(output: bytes, record) -> dict:
    document = GltfDocument.from_bytes(output)
    outer = record.plan.garments[-1].name  # a skirt on a clothed avatar has a liner under it (S2)
    return next(m for m in document.materials if m.get("name", "").startswith(outer)), document


ACCEPTANCE = [
    # prompt, finish, pattern, alpha mode, template
    ("red micro bikini", "matte", "none", "OPAQUE", "swim-bikini-triangle-v1"),
    ("black latex bodycon mini dress", "latex", "none", "OPAQUE", "dress-mini-bodycon-v1"),
    ("sheer black lace bodysuit", "matte", "lace", "MASK", "under-bodysuit-v1"),  # unlined lace
    ("black fishnet thigh-highs", "matte", "fishnet", "MASK", "legwear-thigh-highs-v1"),
    ("pink sequin bodysuit", "sequin", "sequin", "OPAQUE", "under-bodysuit-v1"),
]


@pytest.mark.parametrize(("prompt", "finish", "pattern", "alpha", "template_id"), ACCEPTANCE)
async def test_the_style_acceptance_looks(orchestrator, store, toon_avatar, prompt, finish, pattern, alpha,
                                          template_id):
    record, output = await dress(orchestrator, store, toon_avatar, prompt)
    assert record.state == "completed", record.error
    report = record.fit_report
    assert report.passed and report.humanoid_valid and report.skeleton_preserved, report
    plan = record.plan
    assert plan.template_id == template_id
    assert (plan.material.finish, plan.material.pattern) == (finish, pattern)

    material, document = garment_material(output, record)
    assert material.get("alphaMode", "OPAQUE") == alpha
    mtoon = material["extensions"]["VRMC_materials_mtoon"]  # still toon-shaded like her clothes
    if pattern != "none":
        texture = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        assert mtoon["shadeMultiplyTexture"]["index"] == texture
        image = document.gltf["images"][document.gltf["textures"][texture]["source"]]
        assert image["mimeType"] == "image/png"
    if finish != "matte":
        assert "matcapTexture" in mtoon and any(mtoon["parametricRimColorFactor"])
    if alpha != "OPAQUE":
        assert mtoon["outlineWidthMode"] == "none"


async def test_an_opaque_dress_is_an_everyday_dress_and_a_sheer_one_is_gated(orchestrator, store, toon_avatar):
    record, _ = await dress(orchestrator, store, toon_avatar, "black bodycon mini dress", adult=False)
    assert record.state == "completed", record.error
    assert record.plan.requires_adult is False

    record, output = await dress(orchestrator, store, toon_avatar, "sheer black bodycon mini dress", adult=False)
    assert record.state == "rejected" and record.reason == "requires_adult_declaration"
    assert "see-through dress" in record.error
    assert output is None and record.fit_report.replaced_garments == []


async def test_a_lace_top_is_lined_and_needs_no_declaration(orchestrator, store, toon_avatar):
    record, output = await dress(orchestrator, store, toon_avatar, "white lace crop cami", adult=False)
    assert record.state == "completed", record.error
    assert record.plan.material.lined and not record.plan.requires_adult
    material, _ = garment_material(output, record)
    assert material.get("alphaMode", "OPAQUE") == "OPAQUE"
    assert "baseColorTexture" in material["pbrMetallicRoughness"]  # the lace still shows


async def test_a_pattern_tile_has_the_same_physical_size_on_any_garment(orchestrator, store, toon_avatar):
    """UVs are metres of fabric scaled by the tile size, so a diamond is ~1.4 cm on a stocking."""
    record, output = await dress(orchestrator, store, toon_avatar, "black fishnet thigh-highs")
    document = GltfDocument.from_bytes(output)
    node = next(n for n in document.nodes if n.get("name") == record.plan.name)
    primitive = document.meshes[node["mesh"]]["primitives"][0]
    uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"])
    position = document.read_accessor(primitive["attributes"]["POSITION"])
    # Along a stocking's length: tiles per metre of height is the pattern's scale.
    span_v = uv[:, 1].max() - uv[:, 1].min()
    span_y = position[:, 1].max() - position[:, 1].min()
    assert span_v / span_y == pytest.approx(record.plan.material.texture_scale, rel=0.35)


@pytest.mark.parametrize(
    "prompt",
    [
        "red micro bikini",
        "black string bikini",
        "black high-cut one-piece swimsuit",
        "black lace garter set",
        "black harness bralette",
        "red plunging bodysuit",
        "red v-neck cocktail dress",
        "black backless satin slip dress",
        "navy plaid micro mini skirt",
        "neon green pvc leggings",
        "black latex catsuit",
    ],
)
async def test_every_cut_and_strap_network_completes_and_passes(orchestrator, store, toon_avatar, prompt):
    record, output = await dress(orchestrator, store, toon_avatar, prompt)
    assert record.state == "completed", record.error
    assert record.fit_report.passed and record.fit_report.humanoid_valid, record.fit_report
