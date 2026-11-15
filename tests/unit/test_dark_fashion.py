"""The four dark-fashion garments: selection, construction, and the clothes they must not replace."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.dark_fashion import apply_construction
from wardrobe.geometry.mesh import section_ranges
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

HIGH_NECK = {"collar": "high", "zipper": "center-front"}
BUCKLES = {"buckles": 3}
CORSET = {"channels": 8, "busk": True}


@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def _params(measurements, construction=None, **style):
    metadata = dict(style)
    if construction is not None:
        metadata["construction"] = construction
    return FitParameters(measurements=measurements, metadata=metadata)


def _names(mesh) -> list[str]:
    return [name for name, _, _ in section_ranges(mesh)]


def _section(mesh, prefix: str) -> np.ndarray:
    tris = mesh.indices.reshape(-1, 3)
    keep = np.zeros(mesh.vertex_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name == prefix or name.startswith(prefix):
            keep[np.unique(tris[first:first + count])] = True
    return mesh.positions[keep]


def _mirrored(points: np.ndarray, tol: float = 0.003) -> bool:
    if points.size == 0:
        return False
    for point in points:
        if point[0] < 0.004:
            continue
        mirror = np.array([-point[0], point[1], point[2]])
        if float(np.linalg.norm(points - mirror, axis=1).min()) > tol:
            return False
    return True


def _close_to(detail: np.ndarray, cloth: np.ndarray, limit: float) -> bool:
    """No sampled detail vertex floats more than ``limit`` off the cloth."""
    sample = detail[:: max(len(detail) // 40, 1)]
    distance = np.linalg.norm(sample[:, None, :] - cloth[None, :, :], axis=2).min(axis=1)
    return float(distance.max()) < limit


def test_the_four_phrases_select_their_own_templates_and_the_old_ones_stay(template_catalog):
    chosen = {
        "high-neck latex catsuit": "jumpsuit-high-neck-latex-v1",
        "black high-neck latex catsuit": "jumpsuit-high-neck-latex-v1",
        "leather garter belt with stockings": "under-leather-garter-v1",
        "buckle-front leather mini dress": "dress-buckle-leather-mini-v1",
        "structured leather corset": "top-structured-leather-corset-v1",
    }
    unchanged = {
        "black latex catsuit": "jumpsuit-catsuit-v1",
        "black corset": "top-corset-v1",
        "black bustier": "top-corset-v1",
        "black garter belt": "under-garter-set-v1",
        "black bodycon mini dress": "dress-mini-bodycon-v1",
        "black suspender belt": "under-garter-set-v1",
    }
    for prompt, template_id in {**chosen, **unchanged}.items():
        plan = plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog)
        ids = [garment.template_id for garment in plan.garments]
        # The leather belt is built as the classic suspender belt once hosiery planning runs.
        if template_id == "under-leather-garter-v1":
            assert "under-suspender-belt-v1" in ids, (prompt, ids)
            assert any(garment.role == "connector" for garment in plan.garments)
        else:
            assert template_id in ids, (prompt, ids)


def test_opaque_fashion_is_not_gated_and_the_garter_still_is(template_catalog):
    for prompt in ("high-neck latex catsuit", "buckle-front leather mini dress", "structured leather corset"):
        plan = plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog)
        assert plan.requires_adult is False, prompt
        assert plan.material.finish in {"latex", "leather"}
        assert plan.material.opacity == 1.0
    garter = plan_outfit_stack(OutfitRequest(prompt="leather garter belt with stockings"), template_catalog)
    assert garter.requires_adult is True
    belt = next(g for g in garter.garments if g.template_id == "under-suspender-belt-v1")
    stockings = next(g for g in garter.garments if g.category == "legwear")
    straps = next(g for g in garter.garments if g.role == "connector")
    assert belt.material.finish == "leather"
    assert belt.hosiery.belt.strap_count == 4
    assert belt.hosiery.belt.clasp is True
    assert stockings.material.opacity == 1.0
    assert stockings.material.exposes_body is False
    assert straps.material.finish == "leather"
    assert straps.requires_adult is True
    # The old garter set is still just the set: no suspender belt, no connector.
    old = plan_outfit_stack(OutfitRequest(prompt="black garter belt"), template_catalog)
    assert [g.template_id for g in old.garments] == ["under-garter-set-v1"]
    assert old.hosiery is None


def test_the_high_neck_catsuit_has_a_collar_zipper_sleeves_and_legs(measurements):
    # The builder reads the sleeve off the parameters, not the hem word.
    high_params = _params(measurements, HIGH_NECK)
    high_params.sleeve_length = "long"
    plain_params = _params(measurements)
    plain_params.sleeve_length = "long"
    plain = build_garment("catsuit", plain_params, silhouette="slim", hem="ankle")
    high = apply_construction(build_garment("catsuit", high_params, silhouette="slim", hem="ankle"), high_params)

    plain_names = _names(plain)
    names = _names(high)
    assert "collar" not in plain_names and "zipper" not in plain_names
    assert "collar" in names and "zipper" in names
    assert any(name.startswith("catsuit-left") or name.startswith("elastic-catsuit-left") for name in names)
    assert any(name.startswith("catsuit-right") or name.startswith("elastic-catsuit-right") for name in names)
    assert any(name.startswith("sleeve-left") for name in names)
    assert any(name.startswith("sleeve-right") for name in names)
    # The collar rises past the ordinary catsuit's neckline. The sleeves of both
    # reach the shoulder, so the comparison is the shell, not the whole mesh.
    assert _section(high, "collar")[:, 1].max() > _section(plain, "catsuit-body")[:, 1].max() + 0.04
    assert not high.validate()

    collar = _section(high, "collar")
    body = _section(high, "catsuit-body")
    zipper = _section(high, "zipper")
    # The collar overlaps the neck of the shell, and the zipper lies on that shell.
    assert collar[:, 1].min() < body[:, 1].max()
    assert _mirrored(collar)
    assert _mirrored(zipper)
    assert _close_to(zipper, np.vstack([body, collar]), 0.015)
    assert float(np.mean(zipper[:, 2])) > 0.0


def test_the_buckle_dress_has_three_symmetric_front_straps(measurements):
    params = _params(measurements, BUCKLES)
    mesh = apply_construction(build_garment("dress", params, silhouette="sheath", hem="mini"), params)
    names = _names(mesh)
    assert names.count("dress-bodice") >= 1 or any(n.startswith("dress-") for n in names)
    assert [n for n in names if n.startswith("strap-")] == ["strap-0", "strap-1", "strap-2"]
    assert [n for n in names if n.startswith("hardware-buckle-")] == [
        "hardware-buckle-0", "hardware-buckle-1", "hardware-buckle-2",
    ]
    assert not mesh.validate()
    cloth = np.vstack([_section(mesh, "dress-bodice"), _section(mesh, "dress-skirt")])
    for index in range(3):
        strap = _section(mesh, f"strap-{index}")
        buckle = _section(mesh, f"hardware-buckle-{index}")
        assert _mirrored(strap)
        assert abs(float(buckle[:, 0].mean())) < 0.004
        assert float(strap[:, 2].mean()) > 0.02  # across the front, not through the back
        assert _close_to(strap, cloth, 0.02)
        assert _close_to(buckle, strap, 0.02)
    heights = [float(_section(mesh, f"strap-{i}")[:, 1].mean()) for i in range(3)]
    gaps = [heights[i] - heights[i + 1] for i in range(2)]
    assert abs(gaps[0] - gaps[1]) < 0.01


def test_the_structured_corset_has_channels_a_busk_and_finished_edges(measurements):
    params = _params(measurements, CORSET, straps="shoulder", neckline="sweetheart")
    plain = build_garment("corset", _params(measurements, straps="shoulder", neckline="sweetheart"))
    shaped = apply_construction(build_garment("corset", params), params)
    assert not any(name.startswith("channel-") for name in _names(plain))
    names = _names(shaped)
    channels = [name for name in names if name.startswith("channel-")]
    assert len(channels) == 8
    assert "busk" in names
    assert "binding-top" in names and "binding-hem" in names
    assert len([name for name in names if name.startswith("hardware-stud-")]) == 5
    assert not shaped.validate()
    cloth = _section(shaped, "corset")
    for name in channels:
        welt = _section(shaped, name)
        assert _close_to(welt, cloth, 0.02)
    assert _mirrored(_section(shaped, "busk"))
    # The centre-front point: the hem is lower on the front than at the side.
    front = cloth[np.abs(cloth[:, 0]) < 0.015]
    side = cloth[np.abs(cloth[:, 0]) > np.percentile(np.abs(cloth[:, 0]), 80)]
    assert float(front[:, 1].min()) < float(side[:, 1].min()) - 0.012


def test_a_plain_catsuit_corset_and_dress_gain_nothing_from_the_construction_pass(measurements):
    for category, silhouette, hem in (("catsuit", "slim", "ankle"), ("dress", "sheath", "mini"), ("corset", "slim", "mini")):
        params = _params(measurements)
        if category == "catsuit":
            params.sleeve_length = "long"
        mesh = build_garment(category, params, silhouette=silhouette, hem=hem)
        again = apply_construction(mesh, params)
        assert again is mesh
