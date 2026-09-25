"""Hosiery through the real pipeline, on the tall calibration mannequin (adult proportions, VRM 1.0).

One fit model: the stockings publish their tops, the straps clip to exactly
those points, the hardware sits on them, and the hem is solved against them.
Each look is built once per module and inspected from several sides.

The jobs carry ``depictsAdult: true``, the caller's attestation the API already
takes for an upload, as every intimate-wear test in this suite does. The same
looks without it are refused (``test_the_gate_still_refuses_an_undeclared_avatar``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.hosiery import fit as hosiery_fit
from wardrobe.hosiery.hardware import CLASP_H
from wardrobe.hosiery.poses import POSES, skin_mesh, transforms
from wardrobe.hosiery.suspender_straps import STRETCH_ERROR
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument

ROOT = Path(__file__).resolve().parents[2]
TALL = next(b for b in CALIBRATION_BODIES if b.name == "calibration-c-tall")
CLASSIC = {"prompt": "black bodycon mini dress", "hosiery": {"type": "sheer", "denier": 20, "topStyle": "wide"},
           "suspenderBelt": {"style": "classic"}}


def run(tmp: Path, outfit: dict, *, adult: bool = True, spec: str = "VRM1"):
    """One job; returns (record, output bytes, the pipeline context the connector saw)."""
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                                wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                                catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
    seen: dict = {}
    original = hosiery_fit.fit_connector

    def spy(context):  # observe, never change: the result is the connector's own
        seen["context"] = context
        return original(context)

    async def go():
        await store.put("sources/body.vrm", build_vrm(TALL, spec=spec))
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/body.vrm", "avatarId": "mannequin", "depictsAdult": adult},
            "outfit": outfit, "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orchestrator.run_now(request)
        data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
        return record, data

    hosiery_fit.fit_connector = spy
    try:
        record, data = asyncio.run(go())
    finally:
        hosiery_fit.fit_connector = original
    return record, data, seen.get("context")


@pytest.fixture(scope="module")
def looks(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("hosiery")
    out = {}
    for name, outfit in {
        "glimpse": {**CLASSIC, "reveal": {"level": "glimpse"}},
        "discreet": {**CLASSIC, "reveal": {"level": "discreet"}},
        "statement": {**CLASSIC, "reveal": {"level": "statement"}},
        "explicit": {**CLASSIC, "reveal": {"level": "discreet", "explicitHemLength": 30}},
        "seamed": {"prompt": "vintage_seamed", "preset": "vintage_seamed"},
        "fishnet": {"prompt": "fishnet_black", "preset": "fishnet_black"},
    }.items():
        out[name] = run(tmp / name, outfit)
    return out


def _nodes(data: bytes) -> list[tuple[dict, dict]]:
    document = GltfDocument.from_bytes(data)
    return [(node, document.meshes[node["mesh"]]) for node in document.nodes
            if (node.get("extras") or {}).get("wardrobeForge", {}).get("kind") == "garment"]


def test_every_hosiery_look_completes_and_validates(looks):
    for name, (record, data, _context) in looks.items():
        assert record.state is JobState.COMPLETED, (name, record.error)
        assert record.fit_report.passed, (name, record.fit_report.errors)
        assert record.fit_report.hosiery is not None
        assert data is not None


def test_stockings_publish_their_fitted_tops_and_the_clips_lie_on_the_band(looks):
    for name, (_record, _data, context) in looks.items():
        tops = context.stocking_tops
        assert set(tops) == {"left", "right"}, name
        for top in tops.values():
            assert top.top_y > top.bottom_y
            for clip in top.clips.values():
                assert 0.0 < clip.v <= top.width_m
                assert np.isclose(np.linalg.norm(clip.normal), 1.0)
        distances = context.fit_report.hosiery["clips"]["bandDistanceMm"]
        assert distances and max(distances.values()) <= 2.0, name


def test_the_wide_top_is_five_centimetres(looks):
    _record, _data, context = looks["glimpse"]
    for top in context.stocking_tops.values():
        assert top.width_m == pytest.approx(0.05, abs=0.004)


def test_the_straps_end_at_the_published_clips(looks):
    """The connector reads the contract; it never recomputes a stocking top."""
    _record, _data, context = looks["glimpse"]
    for strap in context.connector.straps:
        clip = context.stocking_tops[strap.side].clips[strap.clip]
        clasp_top = clip.position - clip.tangent * (CLASP_H / 2.0)
        assert np.linalg.norm(strap.path[-1] - clasp_top) < 0.004, strap.name
        assert strap.path[0][1] > context.belt.bottom_y  # and start over the belt


def test_four_straps_or_six(looks):
    assert len(looks["glimpse"][2].connector.straps) == 4
    assert len(looks["seamed"][2].connector.straps) == 6  # the vintage preset's high-waisted belt


def test_strap_tension_is_measured_in_every_pose_and_stays_within_limits(looks):
    for name in ("glimpse", "seamed", "fishnet"):
        report = looks[name][0].fit_report.hosiery
        tension = report["straps"]["tension"]
        assert set(tension) >= {"FL", "FR", "RL", "RR"}
        for code, strap in tension.items():
            assert set(strap["stretch"]) == set(POSES)
            assert strap["stretch"]["stand"] == pytest.approx(-0.015, abs=0.002)  # rest = standing + 1.5%
            for pose in POSES:
                assert strap["stretch"][pose] <= STRETCH_ERROR, (name, code, pose)
        assert not report["errors"], (name, report["errors"])


def test_hardware_is_opaque_and_rigid_in_every_pose(looks):
    _record, data, context = looks["glimpse"]
    document = GltfDocument.from_bytes(data)
    straps = next(mesh for node, mesh in _nodes(data) if "Straps" in node["name"])
    hardware = document.materials[straps["primitives"][1]["material"]]
    assert hardware.get("alphaMode", "OPAQUE") == "OPAQUE"
    # Each clasp moves as one piece: distances within it do not change posed.
    built = next(layer for layer in context.built if layer.plan.role == "connector")
    mesh = built.mesh
    from wardrobe.geometry.mesh import section_ranges

    tris = mesh.indices.reshape(-1, 3)
    names = [s.name for s in built.segments]
    for pose in POSES:
        table = transforms(pose, hosiery_fit.forward(context), context.measurements.bone_positions, names)
        posed = skin_mesh(mesh.positions, mesh.joints, mesh.weights, names, table)
        for section, first, count in section_ranges(mesh):
            if not section.startswith("hardware-clasp"):
                continue
            verts = np.unique(tris[first : first + count])
            rest = np.linalg.norm(mesh.positions[verts] - mesh.positions[verts[0]], axis=1)
            moved = np.linalg.norm(posed[verts] - posed[verts[0]], axis=1)
            assert np.abs(rest - moved).max() < 1e-4, (pose, section)


def test_the_stocking_is_four_primitives_and_the_leg_is_darker_at_the_sides(looks):
    _record, data, _context = looks["glimpse"]
    document = GltfDocument.from_bytes(data)
    stockings = next(mesh for node, mesh in _nodes(data) if "Stockings" in node["name"])
    materials = [document.materials[p["material"]] for p in stockings["primitives"]]
    leg, band, edge = materials[0], materials[1], materials[2]
    assert leg["alphaMode"] == "BLEND" and "baseColorTexture" in leg["pbrMetallicRoughness"]
    assert band.get("alphaMode", "OPAQUE") == "OPAQUE" and edge.get("alphaMode", "OPAQUE") == "OPAQUE"
    assert sum(edge["pbrMetallicRoughness"]["baseColorFactor"][:3]) <= sum(
        band["pbrMetallicRoughness"]["baseColorFactor"][:3])
    report = looks["glimpse"][0].fit_report.hosiery["materials"]
    assert report["sideOpacity"] > report["baseOpacity"]


def test_a_back_seam_runs_down_the_back_of_each_leg_and_stays_there_posed(looks):
    _record, _data, context = looks["seamed"]
    built = next(layer for layer in context.built if layer.plan.category == "legwear")
    mesh = built.mesh
    from wardrobe.geometry.mesh import section_ranges

    tris = mesh.indices.reshape(-1, 3)
    forward = hosiery_fit.forward(context)
    names = [s.name for s in built.segments]
    for section, first, count in section_ranges(mesh):
        if not section.startswith("hosiery-seam"):
            continue
        side = section.rsplit("-", 1)[1]
        verts = np.unique(tris[first : first + count])
        seam = mesh.positions[verts].astype(np.float64)
        knee = context.measurements.bone_positions[f"{side}LowerLeg"]
        thigh = seam[seam[:, 1] > knee[1]]
        assert (thigh[:, 2] * forward < knee[2] * forward).all()  # behind the leg all the way down
        assert np.ptp(thigh[:, 0]) < 0.03  # no spiral: it keeps to one line
        # Posed, it moves with the stocking under it: same weights as the vertices it sits on.
        source = np.asarray(mesh.metadata["hosieryWeightSource"]["sources"])
        first_new = mesh.metadata["hosieryWeightSource"]["first"]
        table = transforms("walk", forward, context.measurements.bone_positions, names)
        posed = skin_mesh(mesh.positions, mesh.joints, mesh.weights, names, table)
        new = np.arange(first_new, first_new + source.size)
        gap_rest = np.linalg.norm(mesh.positions[new] - mesh.positions[source], axis=1)
        gap_posed = np.linalg.norm(posed[new] - posed[source], axis=1)
        assert np.abs(gap_rest - gap_posed).max() < 1e-4


def test_fishnet_uses_the_same_contract(looks):
    record, data, context = looks["fishnet"]
    assert len(context.stocking_tops["left"].clips) >= 2
    document = GltfDocument.from_bytes(data)
    stockings = next(mesh for node, mesh in _nodes(data) if "Stockings" in node["name"])
    assert document.materials[stockings["primitives"][0]["material"]]["alphaMode"] == "MASK"
    assert record.fit_report.hosiery["materials"]["pattern"] == "fishnet"


@pytest.mark.parametrize("level", ["discreet", "glimpse", "statement"])
def test_each_reveal_level_is_achieved_on_the_mannequin(looks, level):
    reveal = looks[level][0].fit_report.hosiery["reveal"]
    assert reveal["requested"] == level and reveal["achieved"] == level, reveal
    visible = set(reveal["visibleIn"])
    assert visible == {"discreet": set(), "glimpse": {"sit"}, "statement": set(POSES)}[level]


def test_the_hems_order_by_level_and_the_reveal_moves_only_the_outer_hem(looks):
    hems = {level: looks[level][0].fit_report.hosiery["reveal"]["hemY"] for level in
            ("discreet", "glimpse", "statement")}
    assert hems["discreet"] < hems["glimpse"] < hems["statement"]
    tops = {level: looks[level][2].stocking_tops["left"].top_y for level in hems}
    assert max(tops.values()) - min(tops.values()) < 1e-6  # stockings never move for a hem


def test_an_explicit_length_wins_and_the_report_says_what_it_gives(looks):
    reveal = looks["explicit"][0].fit_report.hosiery["reveal"]
    assert reveal["explicitLength"] is True
    assert reveal["achieved"] != "discreet" and reveal["notes"]


def test_the_belt_is_under_the_dress_by_garment_order(looks):
    record, data, context = looks["glimpse"]
    order = [layer["role"] for layer in record.fit_report.hosiery["layering"]]
    assert order.index("foundation") < order.index("legwear") < order.index("connector") < order.index(
        "one-piece")
    hem = record.fit_report.hosiery["reveal"]["hemY"]
    assert context.belt.bottom_y > hem + 0.05  # the whole belt is above the hem, inside the dress


def test_the_fit_report_block_is_json(looks):
    json.dumps(looks["glimpse"][0].fit_report.hosiery)


def test_the_gate_still_refuses_an_undeclared_avatar(tmp_path):
    record, _data, _context = run(tmp_path, {**CLASSIC, "reveal": {"level": "glimpse"}}, adult=False)
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.ADULT_DECLARATION_REQUIRED


def test_a_vrm0_avatar_gets_the_same_design(tmp_path):
    """VRM 0.x faces -Z: the poses, clips and seam all have to know."""
    record, _data, context = run(tmp_path, {**CLASSIC, "reveal": {"level": "glimpse"}}, spec="VRM0")
    if record.state is JobState.REJECTED:  # the VRM 0.x calibration body's terms disallow intimate wear
        assert record.reason is FailureReason.INTIMATE_NOT_PERMITTED
        return
    assert record.fit_report.hosiery["reveal"]["achieved"] is not None
    assert all(s.stretch["sit"] <= STRETCH_ERROR for s in context.connector.straps)


def test_a_look_without_hosiery_has_no_hosiery_block(tmp_path):
    record, _data, _context = run(tmp_path, {"prompt": "red bodycon mini dress"})
    assert record.state is JobState.COMPLETED and record.fit_report.hosiery is None
