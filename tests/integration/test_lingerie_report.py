"""L8/L9. The fit report's lingerie block: elastic tension per edge and pose, and the garment rules.

Built on the fashion-fit form the repository declares adult, through the real pipeline,
as the collection sheet is. The rules are warnings, never errors: a look with a rule
warned is still ``passed`` (the plan rolls thresholds out as warnings first).
"""

from __future__ import annotations

import math

import pytest

from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.lingerie.contract import ElasticSpec
from wardrobe.lingerie.elastic import ELASTICS, FittedElasticEdge
from wardrobe.lingerie.validate import elastic_rules
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.fashion_body import build_fit_form, fit_form

FORM = "fit-form-a-misses"


def test_pressure_is_laplace_law_over_the_elastic_width():
    spec = ElasticSpec("t", 10.0, ((0.0, 0.0), (0.1, 1.0), (0.2, 2.0)), cut_ratio=0.9)
    edge = FittedElasticEdge("waist", "waist", "brief", spec, pattern_length=0.66,
                             worn={"stand": 0.66, "sit": 0.70})
    assert edge.rest_length == pytest.approx(0.594)
    strain = 0.66 / 0.594 - 1.0
    assert edge.strain("stand") == pytest.approx(strain)
    radius = 0.66 / (2 * math.pi)
    assert edge.pressure_kpa("stand") == pytest.approx(spec.force(strain) / (radius * 0.010) / 1000.0)
    assert edge.strain("sit") > edge.strain("stand")


def test_a_slack_edge_gapes_and_is_warned():
    edge = FittedElasticEdge("leg-x", "leg", "brief", ELASTICS["picot-8"], pattern_length=0.5,
                             worn={"stand": 0.5, "sit": 0.43})
    rows = {r["id"]: r for r in elastic_rules(edge, "brief")}
    assert rows["brief.leg-x.gape"]["status"] == "warn"
    assert rows["brief.leg-x.strain.stand"]["status"] == "pass"  # cut 0.90: 11% standing


def test_every_library_elastic_pulls_harder_the_more_it_is_stretched():
    for spec in ELASTICS.values():
        forces = [spec.force(s) for s in (0.0, 0.05, 0.1, 0.2, 0.4, 0.8)]
        assert forces[0] == 0.0 and forces == sorted(forces), spec.name


async def test_the_lace_set_reports_its_elastics_and_rules(orchestrator, store):
    assert declared_adult(FORM)
    await store.put("sources/form.vrm", build_fit_form(fit_form(FORM)))
    record = await orchestrator.run_now(CreateJobRequest.model_validate({
        "avatar": {"storageKey": "sources/form.vrm", "avatarId": FORM, "depictsAdult": True},
        "outfit": {"prompt": "italian_lace_thong_set", "preset": "italian_lace_thong_set"},
        "options": {"renderPreview": False, "engine": "native"},
    }))
    assert record.state is JobState.COMPLETED, record.error
    block = record.fit_report.lingerie
    pieces = {p["kind"]: p for p in block["pieces"]}
    assert set(pieces) == {"bra-block", "brief-block"}
    brief = {e["name"]: e for e in pieces["brief-block"]["elastics"]}
    assert {"waist", "leg-negativeX", "leg-positiveX"} <= set(brief)
    waist = brief["waist"]
    assert set(waist["strain"]) == {"stand", "walk", "sit"}
    # Cut 10% short and sewn to an edge that fits her: about 11% standing, within §5.
    assert 0.05 <= waist["strain"]["stand"] <= 0.15
    assert 0.4 <= waist["pressureKpa"]["stand"] <= 1.5
    underband = pieces["bra-block"]["elastics"][0]
    assert underband["name"] == "underband" and 0.10 <= underband["strain"]["stand"] <= 0.25
    ids = {r["id"] for p in block["pieces"] for r in p["rules"]}
    assert {"bra.cups.symmetry", "bra.underband.level", "brief.gusset.midline"} <= ids
    # Warnings, never errors: the rules do not decide whether the look passed.
    assert record.fit_report.passed
    assert block["rulesWarned"] == len(block["warnings"])
    assert all(any(w in r for r in record.fit_report.warnings) for w in block["warnings"])


async def test_a_look_without_lingerie_has_no_lingerie_block(orchestrator, store, stored_avatar):
    from tests.conftest import job_request

    record = await orchestrator.run_now(CreateJobRequest.model_validate(
        job_request(stored_avatar, "red bodycon mini dress")))
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.lingerie is None
    assert "lingerie" not in record.fit_report.model_dump(by_alias=True)


async def test_a_sheer_brief_keeps_an_opaque_lined_gusset(orchestrator, store):
    """L7. The gusset is lined: a sheer brief was see-through there too."""
    from wardrobe.vrm.document import GltfDocument

    await store.put("sources/form.vrm", build_fit_form(fit_form(FORM)))
    record = await orchestrator.run_now(CreateJobRequest.model_validate({
        "avatar": {"storageKey": "sources/form.vrm", "avatarId": FORM, "depictsAdult": True},
        "outfit": {"prompt": "black sheer hipster briefs", "templateId": "under-hipster-v2"},
        "options": {"renderPreview": False, "engine": "native"},
    }))
    assert record.state is JobState.COMPLETED, record.error
    document = GltfDocument.from_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    materials = {m["name"]: m for m in document.gltf["materials"]}
    gusset = next((m for name, m in materials.items() if " Gusset [" in name), None)
    assert gusset is not None, sorted(materials)
    assert gusset.get("alphaMode", "OPAQUE") == "OPAQUE"
    panel = next(m for name, m in materials.items()
                 if "Briefs [" in name)  # the panels: not the Gusset, not the Trim
    assert panel.get("alphaMode") == "BLEND"
