"""Base Body Prep and layered outfits: undress once, dress in layers, one VRM.

The acceptance table these follow:

    Tops + Bottoms -> bra + briefs + dress      source clothes gone, all three new pieces present
    Onepiece -> bra + briefs + dress            onepiece removed: the stack covers upper + lower
    Onepiece -> bra only                        onepiece retained
    incomplete body under the onepiece          fails closed; nothing is invented
    an unknown mesh called "Cloth123"           never removed
    modification prohibited / no adult decl.    rejected before anything is stripped
    underwear + sheer dress / opaque dress      the underwear survives under both
    Forge underwear -> a new outer layer        recognised by its Forge tag and kept
    any job                                     the stored source is byte-identical afterwards
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid, primitive_materials
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.vrm.build import CALIBRATION_BODIES, BodyProportions, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document

TOPS = "F00_000_01_Tops_01_CLOTH"
BOTTOMS = "F00_000_01_Bottoms_01_CLOTH"
ONEPIECE = "F00_000_01_Onepiece_01_CLOTH"
LINGERIE_DRESS = "black lace bralette + matching briefs + red bodycon mini dress"


@pytest.fixture(scope="module")
def body() -> bytes:
    """VRM 1.0: its terms allow what the VRM 0.x calibration body's disallow."""
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


async def dress(orchestrator, store, source: bytes, prompt: str, *, adult: bool = True, **options):
    await store.put("sources/layered.vrm", source)
    payload = job_request("sources/layered.vrm", prompt, **options)
    payload["avatar"]["depictsAdult"] = adult
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output


def garment_nodes(output: bytes) -> list[dict]:
    document = GltfDocument.from_bytes(output)
    return [node for node in document.nodes if (node.get("extras") or {}).get("wardrobeForge", {}).get("kind")]


def hollow(vrm_bytes: bytes) -> bytes:
    """A body with no skin under the torso: the polygon-saving export some pipelines make."""
    document = GltfDocument.from_bytes(vrm_bytes)
    info = inspect_document(document)
    world = document.world_matrices()
    hips_y = float(world[info.humanoid_bones["hips"]][1, 3])
    chest_y = float(world[info.humanoid_bones["upperChest"]][1, 3])
    skin = document.meshes[0]["primitives"][0]
    positions = document.read_accessor(skin["attributes"]["POSITION"])
    triangles = document.read_accessor(skin["indices"]).reshape(-1, 3)
    centre = positions[triangles].mean(axis=1)
    keep = triangles[(centre[:, 1] < hips_y - 0.02) | (centre[:, 1] > chest_y + 0.05)]
    skin["indices"] = document.add_accessor(keep.reshape(-1, 1).astype(np.uint32))
    return document.to_bytes()


# ----------------------------------------------------------------------
# the strip plan is decided for the whole outfit
# ----------------------------------------------------------------------
async def test_tops_and_bottoms_come_off_and_all_three_layers_go_on(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS)
    assert record.state is JobState.COMPLETED, record.error
    assert sorted(record.fit_report.replaced_garments) == ["bottoms", "tops"]
    worn = primitive_materials(output)
    assert TOPS not in worn and BOTTOMS not in worn
    roles = [node["extras"]["wardrobeForge"]["role"] for node in garment_nodes(output)]
    assert roles == ["foundation", "foundation", "one-piece"]  # inner first; the underwear is kept
    assert [entry["role"] for entry in record.fit_report.layers] == roles
    assert record.fit_report.passed


async def test_a_one_piece_comes_off_for_a_stack_that_covers_what_it_covered(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body, slots=("Onepiece",)), LINGERIE_DRESS)
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.replaced_garments == ["onepiece"]
    assert ONEPIECE not in primitive_materials(output)


async def test_a_bra_alone_does_not_take_a_one_piece_off(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body, slots=("Onepiece",)), "black bralette")
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.replaced_garments == []
    assert ONEPIECE in primitive_materials(output)


async def test_an_unrecognised_mesh_is_never_removed(orchestrator, store, body):
    document = GltfDocument.from_bytes(dress_like_vroid(body))
    document.materials[-1]["name"] = "Cloth123"  # the Bottoms primitive, under a name no convention knows
    record, output = await dress(orchestrator, store, document.to_bytes(), LINGERIE_DRESS)
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.replaced_garments == ["tops"]
    assert "Cloth123" in primitive_materials(output)


# ----------------------------------------------------------------------
# the body under the clothes is checked; nothing is invented
# ----------------------------------------------------------------------
async def test_underwear_on_a_hollow_body_fails_closed(orchestrator, store, body):
    source = dress_like_vroid(hollow(body), slots=("Onepiece",))
    record, output = await dress(orchestrator, store, source, LINGERIE_DRESS)
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.BODY_INCOMPLETE
    assert output is None and record.fit_report.replaced_garments == []


async def test_an_outer_garment_on_a_hollow_body_layers_over_what_she_wears(orchestrator, store, body):
    source = dress_like_vroid(hollow(body), slots=("Onepiece",))
    record, output = await dress(orchestrator, store, source, "red bodycon mini dress")
    assert record.state is JobState.COMPLETED, record.error
    assert ONEPIECE in primitive_materials(output)  # kept: there is nothing under it
    assert any("no body under it" in warning for warning in record.fit_report.warnings)


# ----------------------------------------------------------------------
# refusals happen before anything is stripped
# ----------------------------------------------------------------------
async def test_a_model_that_forbids_modification_is_refused_first(orchestrator, store):
    locked = dress_like_vroid(build_vrm(BodyProportions(name="locked", modification="prohibited"), spec="VRM1"))
    record, output = await dress(orchestrator, store, locked, LINGERIE_DRESS)
    assert record.state is JobState.REJECTED and record.reason is FailureReason.MODIFICATION_NOT_PERMITTED
    assert output is None and record.fit_report.replaced_garments == []


async def test_underwear_without_a_declaration_is_refused_before_undressing(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS, adult=False)
    assert record.state is JobState.REJECTED and record.reason is FailureReason.ADULT_DECLARATION_REQUIRED
    assert output is None and record.fit_report.replaced_garments == []


async def test_underwear_base_adds_a_neutral_foundation_and_is_gated_like_underwear(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), "red bodycon mini dress",
                                 baseBody="underwear-base")
    assert record.state is JobState.COMPLETED, record.error
    assert [g.role for g in record.plan.garments] == ["foundation", "foundation", "one-piece"]
    assert record.fit_report.base_body["mode"] == "underwear-base"

    record, _ = await dress(orchestrator, store, dress_like_vroid(body), "red bodycon mini dress",
                            adult=False, baseBody="underwear-base")
    assert record.reason is FailureReason.ADULT_DECLARATION_REQUIRED


async def test_preserve_layers_over_everything(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS, baseBody="preserve")
    assert record.state is JobState.COMPLETED, record.error
    assert TOPS in primitive_materials(output) and BOTTOMS in primitive_materials(output)


# ----------------------------------------------------------------------
# layers stay layers
# ----------------------------------------------------------------------
@pytest.mark.parametrize(("dress_prompt", "alpha"), [("sheer red bodycon mini dress", "BLEND"),
                                                     ("red bodycon mini dress", "OPAQUE")])
async def test_the_underwear_survives_under_a_sheer_or_an_opaque_dress(orchestrator, store, body, dress_prompt,
                                                                      alpha):
    prompt = f"black lace bralette + matching briefs + {dress_prompt}"
    record, output = await dress(orchestrator, store, dress_like_vroid(body), prompt)
    assert record.state is JobState.COMPLETED, record.error
    document = GltfDocument.from_bytes(output)
    names = [m.get("name", "") for m in document.materials]
    outer = next(m for m in document.materials if m.get("name", "").startswith(record.plan.garments[-1].name))
    assert outer.get("alphaMode", "OPAQUE") == alpha
    fabric = [name for name in names if name.startswith("Black Lace") and " Trim " not in name]
    assert len(fabric) == 2  # bralette and briefs, both there


async def test_the_dress_clears_the_underwear_not_just_the_body(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS)
    document = GltfDocument.from_bytes(output)
    by_name = {node.get("name"): node for node in document.nodes if "mesh" in node}
    points = {}
    for garment in record.plan.garments:
        primitive = document.meshes[by_name[garment.name]["mesh"]]["primitives"][0]
        points[garment.role, garment.name] = document.read_accessor(primitive["attributes"]["POSITION"])
    dress_points = next(p for (role, _), p in points.items() if role == "one-piece")
    briefs = next(p for (role, name), p in points.items() if role == "foundation" and "Brief" in name)
    # Over the briefs' height range, the dress is outside the briefs all the way round.
    low, high = briefs[:, 1].min(), briefs[:, 1].max()
    band = dress_points[(dress_points[:, 1] > low) & (dress_points[:, 1] < high)]
    assert np.hypot(band[:, 0], band[:, 2]).min() >= np.hypot(briefs[:, 0], briefs[:, 2]).min()
    assert record.fit_report.clipping_check in {"passed", "warnings", "clearance-only"}


async def test_every_layer_is_skinned_to_her_one_skeleton(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS)
    document = GltfDocument.from_bytes(output)
    humanoid = set(inspect_document(document).humanoid_bones.values())
    for node in garment_nodes(output):
        joints = set(document.gltf["skins"][node["skin"]]["joints"])
        assert joints and joints <= humanoid


async def test_forge_underwear_is_recognised_and_kept_under_a_new_outer_layer(orchestrator, store, body):
    first, underwear = await dress(orchestrator, store, dress_like_vroid(body), "black lace bralette + matching briefs")
    assert first.state is JobState.COMPLETED, first.error
    second, output = await dress(orchestrator, store, underwear, "red bodycon mini dress")
    assert second.state is JobState.COMPLETED, second.error
    roles = [node["extras"]["wardrobeForge"]["role"] for node in garment_nodes(output)]
    assert roles.count("foundation") == 2 and "one-piece" in roles  # the dress went on over them


async def test_provenance_records_how_the_look_was_made(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), LINGERIE_DRESS)
    forge = GltfDocument.from_bytes(output).gltf["extras"]["wardrobeForge"]
    assert forge["baseBodyMode"] == "replace-outer"
    assert sorted(forge["removedSourceSlots"]) == ["bottoms", "tops"]
    assert [layer["role"] for layer in forge["layers"]] == ["foundation", "foundation", "one-piece"]
    assert record.fit_report.layers[0]["design"]["adultGateRequired"] is True


async def test_the_stored_source_is_never_touched(orchestrator, store, body):
    source = dress_like_vroid(body)
    before = hashlib.sha256(source).hexdigest()
    for prompt, adult in ((LINGERIE_DRESS, True), (LINGERIE_DRESS, False)):  # one completes, one is refused
        await dress(orchestrator, store, source, prompt, adult=adult)
        assert hashlib.sha256(await store.get("sources/layered.vrm")).hexdigest() == before


# ----------------------------------------------------------------------
# the designers' worked example, end to end
# ----------------------------------------------------------------------
DESIGNER_EXAMPLE = (
    "black sheer lace bralette and matching high-leg briefs under a translucent satin mini dress"
)


async def test_the_designers_example_builds_as_specified(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), DESIGNER_EXAMPLE)
    assert record.state is JobState.COMPLETED, record.error
    bralette, briefs, mini = record.plan.garments
    for piece in (bralette, briefs):
        assert (piece.material.pattern, piece.material.alpha_mode, piece.material.lined) == ("lace", "mask", False)
        assert piece.requires_adult
    assert briefs.style.leg_cut == "high"
    assert (mini.material.finish, mini.material.alpha_mode) == ("satin", "blend")
    assert 0.55 <= mini.material.opacity <= 0.85

    document = GltfDocument.from_bytes(output)
    materials = {m.get("name", ""): m for m in document.materials}
    # The lace is cut out, its straps are opaque trim, and the dress is translucent over both.
    lace = next(m for n, m in materials.items() if n.startswith(bralette.name) and " Trim " not in n)
    trim = next(m for n, m in materials.items() if n.startswith(f"{bralette.name} Trim"))
    assert lace["alphaMode"] == "MASK" and trim.get("alphaMode", "OPAQUE") == "OPAQUE"
    assert "baseColorTexture" not in trim["pbrMetallicRoughness"]
    assert record.fit_report.passed
    sheets = [layer["design"] for layer in record.fit_report.layers]
    assert sheets[2]["innerLayersRetained"] == [bralette.name, briefs.name]
    assert sheets[0]["adultGateReason"] == "underwear in see-through fabric"
    assert sheets[2]["maskingPolicy"].startswith("none")


# ----------------------------------------------------------------------
# tights and stockings are layers
# ----------------------------------------------------------------------
async def test_tights_go_under_her_clothes_and_never_take_them_off(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body), "black fishnet tights")
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.replaced_garments == []
    assert TOPS in primitive_materials(output) and BOTTOMS in primitive_materials(output)


async def test_fishnet_tights_under_a_mini_skirt(orchestrator, store, body):
    record, output = await dress(orchestrator, store, dress_like_vroid(body),
                                 "black fishnet tights + red latex pleated mini skirt")
    assert record.state is JobState.COMPLETED, record.error
    tights, skirt = record.plan.garments
    assert (tights.template_id, tights.material.pattern, tights.layer) == ("legwear-tights-v1", "fishnet", 2)
    assert skirt.layer == 3 and record.fit_report.replaced_garments == ["bottoms"]
    assert record.fit_report.passed


async def test_fishnet_legwear_is_gated_like_any_see_through_garment(orchestrator, store, body):
    record, _ = await dress(orchestrator, store, dress_like_vroid(body), "calze a rete nere", adult=False)
    assert record.reason is FailureReason.ADULT_DECLARATION_REQUIRED
    record, _ = await dress(orchestrator, store, dress_like_vroid(body), "black opaque tights", adult=False)
    assert record.state is JobState.COMPLETED, record.error
