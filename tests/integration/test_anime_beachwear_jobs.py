"""AB5. Anime Beachwear through the real pipeline: gated, licensed, fitted, and never overwriting.

The unit tests (``tests/unit/test_anime_beachwear.py``) prove the collection is additive on
paper. These run its designs as the Studio does — an ordinary job carrying a ``design`` block —
and read what comes out:

* the adult declaration and the model's own terms are enforced exactly as for any swimwear;
* each of the twelve designs completes and passes its fit report;
* a new look is a new look: distinct id, distinct storage path, and the bytes of every look
  made before it untouched;
* the halter the collection added is really built, and tied at the back of her neck.

The avatar is the medium VRM 1.0 calibration body, which ``assets/calibration/policy.json``
declares adult; the VRM 0.x one's own terms disallow sexual usage, which is what the licence
test needs.
"""

from __future__ import annotations

import hashlib

import pytest

from wardrobe import collections as registry
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.lingerie.blocks import bra as bra_block

DESIGNS = [d["id"] for d in registry.get("anime-beachwear")["designs"]]


def _payload(key: str, design_id: str, *, adult: bool = True, **design) -> dict:
    return {
        "avatar": {"storageKey": key, "avatarId": "calibration-b-medium", "depictsAdult": adult},
        "outfit": {"prompt": design_id, "design": {"collection": "anime-beachwear", "id": design_id, **design}},
        "options": {"renderPreview": False, "engine": "native"},
    }


async def _run(orchestrator, payload: dict):
    return await orchestrator.run_now(CreateJobRequest.model_validate(payload))


# ---------------------------------------------------------------- the gates are the gates
async def test_without_a_declaration_a_design_is_refused(orchestrator, store, vrm_bytes):
    await store.put("sources/b.vrm", vrm_bytes)
    record = await _run(orchestrator, _payload("sources/b.vrm", "beach-ocean-stripe", adult=False))
    assert record.state == "rejected" and record.reason == "requires_adult_declaration"
    assert record.look is None


async def test_a_model_whose_terms_disallow_it_is_refused_whatever_is_declared(orchestrator, store, vrm0_bytes):
    await store.put("sources/v0.vrm", vrm0_bytes)
    record = await _run(orchestrator, _payload("sources/v0.vrm", "beach-scarlet-scoop"))
    assert record.state == "rejected" and record.reason == "intimate_garments_not_permitted_by_model"
    assert record.look is None


# ---------------------------------------------------------------- every design fits
@pytest.mark.parametrize("design_id", DESIGNS)
async def test_each_design_completes_and_passes_its_fit(orchestrator, store, vrm_bytes, design_id):
    await store.put("sources/b.vrm", vrm_bytes)
    record = await _run(orchestrator, _payload("sources/b.vrm", design_id))
    assert record.state == "completed", record.error
    assert record.fit_report.passed, (design_id, record.fit_report.checks)
    expected = sorted(p["template"] for p in registry.design("anime-beachwear", design_id)["pieces"])
    assert sorted(g.template_id for g in record.plan.garments) == expected


# ---------------------------------------------------------------- nothing is overwritten
async def test_new_looks_never_overwrite_earlier_ones(orchestrator, store, vrm_bytes):
    await store.put("sources/b.vrm", vrm_bytes)
    source = hashlib.sha256(await store.get("sources/b.vrm")).hexdigest()
    first = await _run(orchestrator, _payload("sources/b.vrm", "beach-ocean-stripe"))
    before = await store.get(f"looks/{first.look.id}/look.vrm")
    variant = await _run(orchestrator, _payload("sources/b.vrm", "beach-ocean-stripe", color="navy", finish="gloss"))
    again = await _run(orchestrator, _payload("sources/b.vrm", "beach-ocean-stripe"))
    ids = [first.look.id, variant.look.id, again.look.id]
    assert len(set(ids)) == 3  # the same design asked twice is two looks, not one rewritten
    assert await store.get(f"looks/{first.look.id}/look.vrm") == before
    assert await store.get(f"looks/{variant.look.id}/look.vrm") != before  # navy, not the original green
    assert hashlib.sha256(await store.get("sources/b.vrm")).hexdigest() == source  # her file untouched


# ---------------------------------------------------------------- the new halter is built
async def test_the_halter_is_tied_at_the_back_of_her_neck(orchestrator, store, vrm_bytes, monkeypatch):
    built = []
    original = bra_block.build_bra

    def spy(frame, spec, straps, **kwargs):
        mesh = original(frame, spec, straps, **kwargs)
        built.append((straps.style, mesh.metadata["lingerieBra"]["straps"],
                      frame.params.measurements.bone_positions.get("neck")))
        return mesh

    monkeypatch.setattr(bra_block, "build_bra", spy)
    await store.put("sources/b.vrm", vrm_bytes)
    record = await _run(orchestrator, _payload("sources/b.vrm", "beach-violet-halter"))
    assert record.state == "completed", record.error
    style, straps, neck = built[-1]
    assert style == "halter" and set(straps) == {"left", "right"}
    for strap in straps.values():
        back = strap["back"]
        assert back["source"] == "neck"
        assert abs(back["position"][0]) < 0.04  # beside her spine, not out at her shoulder blade
        assert float(neck[1]) - 0.08 < back["position"][1] < float(neck[1])  # at her nape
