"""DC2/DC3. Sexy Discoteca — All Black, through the whole pipeline.

The acceptance bar from the request, each as a test: the four outfits generate and validate;
the four boots are four different shapes (heel, sole, shaft); her feet stay inside them;
putting other boots on a dress look re-fits only the boots; and the boots stand her on
their heels, recorded so the next pair can stand her on theirs.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline.fashion_collections import COLLECTIONS, boots_prompt, catalogue, dress_prompt
from wardrobe.pipeline.look_presets import LOOK_PRESETS
from wardrobe.vrm import stance
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document

COLLECTION = "sexy-discoteca-black"
PRESETS = [preset["id"] for preset in COLLECTIONS[COLLECTION]["presets"]]
#: Each preset's boots, and the heel and sole it asks for (millimetres).
BOOTS = {
    "discoteca_stiletto_ankle": ("shoes-stiletto-ankle-boots-v1", 95, 6),
    "discoteca_platform": ("shoes-platform-boots-v1", 150, 55),
    "discoteca_combat": ("shoes-combat-boots-v1", 40, 28),
    "discoteca_over_knee": ("shoes-over-knee-boots-v1", 90, 8),
}


@pytest.fixture(scope="module")
def source() -> bytes:
    return build_vrm(CALIBRATION_BODIES[2], spec="VRM1")


async def run(orchestrator, store, source: bytes, prompt: str, preset: str | None = None):
    await store.put("sources/discoteca.vrm", source)
    payload = job_request("sources/discoteca.vrm", prompt)
    if preset:
        payload["outfit"]["preset"] = preset
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed", record.error
    return record, await store.get(f"looks/{record.look.id}/look.vrm")


def garment_nodes(data: bytes) -> dict[str, tuple[dict, np.ndarray]]:
    """templateId -> (node, rest positions) for every Forge garment in the file."""
    document = GltfDocument.from_bytes(data)
    out = {}
    for index in document.mesh_nodes():
        node = document.nodes[index]
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") != "garment":
            continue
        positions = [
            document.read_accessor(p["attributes"]["POSITION"])
            for p in document.meshes[node["mesh"]]["primitives"]
        ]
        out[tag.get("templateId")] = (node, np.unique(np.vstack(positions), axis=0))
    return out


def bones(data: bytes) -> dict[str, np.ndarray]:
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    world = document.world_matrices()
    return {name: world[node][:3, 3] for name, node in info.humanoid_bones.items()}


def test_the_presets_are_the_collection_and_name_its_boots():
    entry = next(c for c in catalogue() if c["id"] == COLLECTION)
    assert [b["letter"] for b in entry["boots"]] == ["A", "B", "C", "D"]
    assert [p["id"] for p in entry["presets"]] == list(BOOTS)
    for preset in PRESETS:
        assert LOOK_PRESETS[preset]["collection"] == COLLECTION
        assert "bodycon mini dress" in LOOK_PRESETS[preset]["prompt"]
    assert dress_prompt(COLLECTION, {"straps": "strapless", "neckline": "sweetheart", "back": "open"}) == (
        "black satin strapless sweetheart open back bodycon mini dress"
    )
    assert (
        boots_prompt(COLLECTION, "over-knee", heel="stiletto")
        == "black stretch leather over-the-knee stiletto boots"
    )


@pytest.mark.parametrize("preset", list(BOOTS))
async def test_each_outfit_generates_validates_and_stands_her_on_its_heels(
    orchestrator, store, source, preset
):
    template, heel, platform = BOOTS[preset]
    record, output = await run(orchestrator, store, source, preset, preset=preset)
    report = record.fit_report
    assert report.passed and report.vrm_valid and report.humanoid_valid and report.weights_valid
    assert report.skeleton_preserved
    assert [g.template_id for g in record.plan.garments][-2:] == ["dress-mini-bodycon-v1", template]
    # Her foot rests on the insole: the stance asks for the boot's heel and sole plus it.
    assert report.stance["heelMm"] == pytest.approx(heel + 4) and report.stance[
        "platformMm"
    ] == pytest.approx(platform + 4)
    document = GltfDocument.from_bytes(output)
    assert stance.read(document, inspect_document(document)).heel_m == pytest.approx((heel + 4) / 1000)
    boots = garment_nodes(output)[template][1]
    assert boots[:, 1].min() == pytest.approx(0.0, abs=0.002)  # on the floor, not through it


async def test_the_four_boots_are_four_shapes(orchestrator, store, source):
    shapes = {}
    for preset, (template, _heel, _platform) in BOOTS.items():
        _record, output = await run(orchestrator, store, source, preset, preset=preset)
        points = garment_nodes(output)[template][1]
        b = bones(output)
        left = points[points[:, 0] * np.sign(b["leftFoot"][0]) > 0]
        top = left[:, 1].max()
        # How much boot there is 15 mm above the floor, behind her heel: a needle, a block, a sole.
        heel_zone = left[(left[:, 1] > 0.01) & (left[:, 1] < 0.02)]
        shapes[preset] = {
            "top_over_knee": top - b["leftLowerLeg"][1],
            "top_over_ankle": top - b["leftFoot"][1],
            "low_width": float(np.ptp(heel_zone[:, 0])) if heel_zone.size else 0.0,
        }
    s = shapes
    # Shafts: ankle < combat (mid-calf) < platform (below the knee) < over the knee.
    assert (
        s["discoteca_stiletto_ankle"]["top_over_ankle"]
        < s["discoteca_combat"]["top_over_ankle"]
        < s["discoteca_platform"]["top_over_ankle"]
    )
    assert s["discoteca_platform"]["top_over_knee"] < 0 < s["discoteca_over_knee"]["top_over_knee"]
    # The platform and the lugged sole are broad near the floor; nothing is wider than they are.
    widest = max(s, key=lambda k: s[k]["low_width"])
    assert widest in {"discoteca_platform", "discoteca_combat"}


async def test_her_feet_stay_inside_the_boots(orchestrator, store, source):
    for preset, (template, _heel, _platform) in BOOTS.items():
        _record, output = await run(orchestrator, store, source, preset, preset=preset)
        document = GltfDocument.from_bytes(output)
        info = inspect_document(document)
        boot = garment_nodes(output)[template][1]
        skins = document.gltf["skins"]
        feet = {
            info.humanoid_bones[f"{side}{bone}"] for side in ("left", "right") for bone in ("Foot", "Toes")
        }
        outside = 0
        total = 0
        for index in document.mesh_nodes():
            node = document.nodes[index]
            if (node.get("extras") or {}).get("wardrobeForge") or node.get("skin") is None:
                continue
            joints = skins[node["skin"]]["joints"]
            for primitive in document.meshes[node["mesh"]]["primitives"]:
                attributes = primitive["attributes"]
                if "JOINTS_0" not in attributes:
                    continue
                p = document.read_accessor(attributes["POSITION"])
                j = document.read_accessor(attributes["JOINTS_0"]).astype(int)
                w = document.read_accessor(attributes["WEIGHTS_0"])
                dominant = np.array(joints)[j[np.arange(len(j)), w.argmax(axis=1)]]
                foot = p[np.isin(dominant, list(feet))]
                for point in foot:
                    total += 1
                    near = boot[np.abs(boot[:, 1] - point[1]) < 0.004]
                    near = near[np.sign(near[:, 0]) == np.sign(point[0])]
                    if near.shape[0] < 3 or not _inside(point[[0, 2]], near[:, [0, 2]]):
                        outside += 1
        assert total > 0
        assert outside / total < 0.01, f"{preset}: {outside} of {total} foot vertices outside the boot"


def _inside(point: np.ndarray, cloud: np.ndarray) -> bool:
    """Is ``point`` inside the convex hull of the 2-D ``cloud``?"""
    centre = cloud.mean(axis=0)
    angles = np.arctan2(cloud[:, 1] - centre[1], cloud[:, 0] - centre[0])
    radius = np.linalg.norm(cloud - centre, axis=1)
    a = np.arctan2(point[1] - centre[1], point[0] - centre[0])
    sector = np.abs(np.angle(np.exp(1j * (angles - a)))) < 0.35
    return bool(sector.any() and np.linalg.norm(point - centre) <= radius[sector].max() + 1e-4)


async def test_changing_boots_refits_only_the_boots(orchestrator, store, source):
    _dress, dress_look = await run(orchestrator, store, source, dress_prompt(COLLECTION))
    record_a, look_a = await run(orchestrator, store, dress_look, boots_prompt(COLLECTION, "stiletto-ankle"))
    record_b, look_b = await run(orchestrator, store, look_a, boots_prompt(COLLECTION, "platform"))
    assert [g.template_id for g in record_b.plan.garments] == ["shoes-platform-boots-v1"]
    worn = garment_nodes(look_b)
    assert "shoes-stiletto-ankle-boots-v1" not in worn and "shoes-platform-boots-v1" in worn
    # The dress is the one made first, carried: only lifted onto the higher heels.
    dress_a, dress_b = garment_nodes(look_a)["dress-mini-bodycon-v1"][1], worn["dress-mini-bodycon-v1"][1]
    rise = record_b.fit_report.stance["liftMm"] / 1000 - record_a.fit_report.stance["liftMm"] / 1000
    assert dress_a.shape == dress_b.shape
    assert np.abs(dress_b - dress_a - np.array([0.0, rise, 0.0])).max() < 2e-4
    assert record_b.fit_report.stance["previous"]["heelMm"] == record_a.fit_report.stance["heelMm"]


async def test_a_dress_on_a_look_with_boots_keeps_her_on_her_heels(orchestrator, store, source):
    record_a, look_a = await run(orchestrator, store, source, boots_prompt(COLLECTION, "combat"))
    record_b, look_b = await run(orchestrator, store, look_a, dress_prompt(COLLECTION))
    assert record_b.fit_report.stance is None  # no shoes in the job: her stance is not touched
    before, after = GltfDocument.from_bytes(look_a), GltfDocument.from_bytes(look_b)
    assert stance.read(after, inspect_document(after)) == stance.read(before, inspect_document(before))
    assert "shoes-combat-boots-v1" in garment_nodes(look_b)
