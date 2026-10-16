"""L6. Stockings with feet: knitted on over her heel and toes and closed under her sole.

``hosiery.foot`` is ``none`` unless asked for, so every look made before L6 keeps its
geometry (the gallery hash check runs on every CI run). Asked for, the stocking is closed
under her: on the calibration mannequin, whose legs end at the ankle joint with no foot
volume, over the end of her leg; on a real avatar, under her sole and out over her toes.
Where there is no foot of hers to knit round at all, it ends above the foot as before and
the fit report says so. Either way the stocking tops the straps clip to are exactly what
they were without a foot.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.integration.test_hosiery_pipeline import CLASSIC, run
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.library import AvatarLibrary
from wardrobe.vrm.document import GltfDocument

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"
FEMALE = LIBRARY / "fem_vroid.vrm"
STATEMENT = {**CLASSIC, "reveal": {"level": "statement"}}


def _stocking_points(data: bytes) -> np.ndarray:
    document = GltfDocument.from_bytes(data)
    node = next(n for n in document.nodes if "Stockings" in n.get("name", ""))
    return np.vstack([document.read_accessor(p["attributes"]["POSITION"])[:, :3]
                      for p in document.meshes[node["mesh"]]["primitives"]]).astype(np.float64)


def test_the_foot_is_off_unless_asked_for():
    from wardrobe.hosiery.options import HosieryOptions

    assert HosieryOptions().foot == "none"
    with pytest.raises(ValueError):
        HosieryOptions(foot="half")


def test_on_the_mannequin_it_closes_over_her_leg_and_the_tops_do_not_move(tmp_path):
    record, data, _ = run(tmp_path, {**STATEMENT, "hosiery": {**STATEMENT["hosiery"], "foot": "full"}})
    plain, plain_data, _ = run(tmp_path / "plain", STATEMENT)
    assert record.state is JobState.COMPLETED, record.error
    assert _stocking_points(data)[:, 1].min() < 0.005 < _stocking_points(plain_data)[:, 1].min()
    _same_tops(record, plain)


def test_with_no_foot_to_knit_round_it_ends_as_before_and_says_so(tmp_path, monkeypatch):
    from wardrobe.hosiery import stockings

    monkeypatch.setattr(stockings, "MIN_FOOT_POINTS", 10**9)
    record, data, _ = run(tmp_path, {**STATEMENT, "hosiery": {**STATEMENT["hosiery"], "foot": "full"}})
    assert record.state is JobState.COMPLETED, record.error
    assert sum("ends above the foot" in w for w in record.fit_report.warnings) == 2  # each leg
    plain, plain_data, _ = run(tmp_path / "plain", STATEMENT)
    assert np.allclose(_stocking_points(data), _stocking_points(plain_data))


def _same_tops(with_foot, without) -> None:
    tops = with_foot.fit_report.hosiery["stockingTop"]
    for side, top in without.fit_report.hosiery["stockingTop"].items():
        for name, clip in top["clips"].items():
            assert np.allclose(tops[side]["clips"][name]["position"], clip["position"], atol=1e-6)


@pytest.mark.skipif(not FEMALE.exists(), reason="the library avatars are fetched by `make library`")
async def test_on_a_real_avatar_the_stocking_closes_under_her_sole(orchestrator, store):
    entry = next(a for a in AvatarLibrary.from_directory(LIBRARY).avatars if a.path == FEMALE)
    await store.put("sources/female.vrm", FEMALE.read_bytes())
    block = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
    block.update(storageKey="sources/female.vrm", depictsAdult=True)

    async def job(foot: str):
        outfit = {**STATEMENT, "hosiery": {**STATEMENT["hosiery"], "foot": foot}}
        record = await orchestrator.run_now(CreateJobRequest.model_validate(
            {"avatar": block, "outfit": outfit, "options": {"renderPreview": False, "engine": "native"}}))
        assert record.state is JobState.COMPLETED, record.error
        return record, await store.get(f"looks/{record.look.id}/look.vrm")

    full, full_data = await job("full")
    none, none_data = await job("none")
    assert not any("ends above the foot" in w for w in full.fit_report.warnings)
    with_foot, without = _stocking_points(full_data), _stocking_points(none_data)
    # Down to her sole (the floor), where it used to stop ~3 cm above the ankle joint.
    assert with_foot[:, 1].min() < 0.01 < without[:, 1].min()
    # Out over her toes: the foot reaches well ahead of where the leg ended.
    assert np.ptp(with_foot[with_foot[:, 1] < 0.03][:, 2]) > 0.15
    _same_tops(full, none)  # the contract the straps clip to does not move
