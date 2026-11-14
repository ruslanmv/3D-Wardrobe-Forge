"""DC1. The stance: feet turned down onto a heel and the body lifted, baked into the rest pose.

Pinned here: the heel asked for is the heel she stands on; the bake is exact and reversible
(heel A then heel B is heel B; any heel then flat is the file she came in); every skin is
still bound at rest; a flat avatar given flat shoes is not touched at all.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from wardrobe.vrm import stance
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document


def _load(data: bytes):
    document = GltfDocument.from_bytes(data)
    return document, inspect_document(document)


@pytest.fixture(scope="module")
def source() -> bytes:
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


def _forward(document, info) -> float:
    world = document.world_matrices()
    foot, toes = info.humanoid_bones["leftFoot"], info.humanoid_bones["leftToes"]
    return 1.0 if world[toes][2, 3] > world[foot][2, 3] else -1.0


def _positions(document) -> np.ndarray:
    out = []
    for node in document.mesh_nodes():
        for primitive in document.meshes[document.nodes[node]["mesh"]]["primitives"]:
            out.append(document.read_accessor(primitive["attributes"]["POSITION"]))
    return np.vstack(out)


def _bake(data: bytes, heel_mm: float, platform_mm: float) -> tuple[bytes, stance.Stance]:
    document, info = _load(data)
    forward = _forward(document, info)
    target = stance.stance_for(
        document, info, heel_m=heel_mm / 1000, platform_m=platform_mm / 1000, forward=forward
    )
    stance.apply(document, info, target, forward=forward)
    return document.to_bytes(), target


def test_solve_reaches_the_heel_it_was_asked_for():
    ankle, ball = np.array([0.0, 0.09, 0.0]), np.array([0.0, 0.04, 0.1])
    for heel in (0.04, 0.08, 0.11):  # this short foot tops out near 125 mm (MAX_PITCH_DEG)
        got = stance.solve(ankle, ball, heel_m=heel, platform_m=0.006, forward=1.0)
        reach = 0.1 * stance.HEEL_CONTACT_SHARE
        turn = math.radians(got.pitch_deg)
        # her heel's contact point, turned about the ankle and lifted
        y = ankle[1] + (0.0 - ankle[1]) * math.cos(turn) + reach * math.sin(turn) + got.lift_m
        assert y == pytest.approx(heel, abs=1e-6)
        assert 0 < got.pitch_deg < stance.MAX_PITCH_DEG


def test_a_flat_sole_is_a_lift_not_a_turn():
    got = stance.solve(
        np.array([0, 0.09, 0]), np.array([0, 0.04, 0.1]), heel_m=0.03, platform_m=0.03, forward=1.0
    )
    assert got.pitch_deg == 0.0 and got.lift_m == pytest.approx(0.03)


def test_higher_heels_turn_the_foot_further(source):
    pitches = [_bake(source, heel, 6)[1].pitch_deg for heel in (40, 95, 140)]
    assert pitches == sorted(pitches) and pitches[0] > 0


def test_the_stance_is_recorded_and_read_back(source):
    data, target = _bake(source, 95, 6)
    document, info = _load(data)
    assert stance.read(document, info) == stance.Stance.from_dict(target.to_dict())
    assert document.nodes[info.humanoid_bones["hips"]]["extras"][stance.STANCE_KEY]["heelMm"] == 95.0


def test_her_lowest_point_rests_on_the_sole(source):
    data, target = _bake(source, 95, 6)
    document, info = _load(data)
    flat, _ = _load(source)
    low_before = _positions(flat)[:, 1].min()
    low_after = _positions(document)[:, 1].min()
    assert low_before == pytest.approx(0.0, abs=0.01)
    assert low_after == pytest.approx(0.006, abs=1e-4)  # on the sole top, not through the floor
    hips = info.humanoid_bones["hips"]
    assert document.world_matrices()[hips][1, 3] - flat.world_matrices()[hips][1, 3] == pytest.approx(
        target.lift_m, abs=1e-6
    )


def test_one_heel_then_another_is_the_other_heel(source):
    a, _ = _bake(source, 95, 6)
    a_then_b, _ = _bake(a, 150, 55)
    b, _ = _bake(source, 150, 55)
    first, second = _load(a_then_b)[0], _load(b)[0]
    assert np.abs(_positions(first) - _positions(second)).max() < 1e-5
    assert np.abs(np.stack(first.world_matrices()) - np.stack(second.world_matrices())).max() < 1e-5


def test_back_to_flat_is_the_file_she_came_in(source):
    heeled, _ = _bake(source, 95, 6)
    document, info = _load(heeled)
    stance.apply(document, info, stance.FLAT, forward=_forward(document, info))
    flat = _load(source)[0]
    assert np.abs(_positions(document) - _positions(flat)).max() < 1e-5
    assert np.abs(np.stack(document.world_matrices()) - np.stack(flat.world_matrices())).max() < 1e-5
    assert stance.STANCE_KEY not in (document.nodes[info.humanoid_bones["hips"]].get("extras") or {})


def test_every_skin_is_still_bound_at_rest(source):
    data, _ = _bake(source, 150, 55)
    document, _ = _load(data)
    world = document.world_matrices()
    for skin in document.gltf["skins"]:
        inverse = document.read_accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        for k, joint in enumerate(skin["joints"]):
            assert np.abs(world[joint] @ inverse[k] - np.eye(4)).max() < 1e-4


def test_the_skeleton_keeps_every_bone_and_name(source):
    data, _ = _bake(source, 95, 6)
    before, after = _load(source), _load(data)
    assert after[1].humanoid_bones == before[1].humanoid_bones
    assert [n.get("name") for n in after[0].nodes] == [n.get("name") for n in before[0].nodes]


def test_flat_shoes_on_flat_feet_touch_nothing(source):
    document, info = _load(source)
    before = document.to_bytes()
    assert stance.apply(document, info, stance.FLAT, forward=_forward(document, info)).flat
    assert document.to_bytes() == before
