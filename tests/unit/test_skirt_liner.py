"""S2. A skirt that takes the place of her bottoms is worn over something.

A VRoid body under its shorts carries the old outfit's tights and undershorts in
its skin texture, so a skirt over the removed shorts showed them. The liner is
slip shorts for every avatar — never underwear, so no declaration is needed to
wear a skirt — and briefs only where the avatar is declared adult.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.domain.looks import OutfitRequest
from wardrobe.pipeline.generate_garment import with_foundation, with_skirt_liner
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> TemplateCatalog:
    return TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")


def lined(catalog, prompt: str, *, adult: bool = False, **overrides):
    request = OutfitRequest(prompt=prompt, mode="template", **overrides)
    return with_skirt_liner(plan_outfit_stack(request, catalog), request, catalog, depicts_adult=adult).garments


@pytest.mark.parametrize("prompt", ["red skater skirt", "navy pleated mini skirt", "black pencil skirt",
                                    "long maxi skirt", "silk lavender a-line midi skirt", "red mini dress"])
def test_every_skirt_is_worn_over_slip_shorts(catalog, prompt):
    garments = lined(catalog, prompt)
    liner = garments[0]
    assert (liner.template_id, liner.role, liner.layer) == ("shorts-slip-v1", "liner", 1)
    assert liner.category == "shorts" and not liner.requires_adult  # nobody needs a declaration for a skirt
    assert garments[-1].category in {"skirt", "dress"}


def test_a_declared_adult_avatar_gets_briefs_instead(catalog):
    liner = lined(catalog, "red skater skirt", adult=True)[0]
    assert liner.category == "underwear" and liner.role == "liner"  # briefs, but never a job-failing foundation


def test_the_request_keeps_its_garments_and_its_choices(catalog):
    """The liner is added after the prompt is split: a tee + a skirt stays a tee and a skirt."""
    garments = lined(catalog, "black long sleeve fitted tee + rose a-line midi skirt")
    assert [g.category for g in garments] == ["shorts", "top", "skirt"]
    assert garments[-1].material.color_name == "rose"
    navy = lined(catalog, "red skater skirt", color="navy")
    assert navy[-1].material.color_name == "navy" and navy[0].material.color_name == "black"


@pytest.mark.parametrize("prompt", ["denim shorts", "white blouse", "black leggings + denim skirt",
                                    "black tights + red skater skirt", "black slip shorts + navy pleated mini skirt"])
def test_nothing_is_added_where_her_hips_are_already_covered_or_there_is_no_skirt(catalog, prompt):
    garments = lined(catalog, prompt)
    assert sum(g.template_id == "shorts-slip-v1" for g in garments) <= 1
    assert all(g.role != "liner" for g in garments) or "slip shorts" in prompt


def test_underwear_base_keeps_every_garment_of_a_layered_prompt(catalog):
    """The same split applies to the foundation a Studio 'underwear-base' job adds."""
    request = OutfitRequest(prompt="black long sleeve fitted tee + rose a-line midi skirt", mode="template")
    garments = with_foundation(plan_outfit_stack(request, catalog), request, catalog).garments
    assert [g.category for g in garments] == ["underwear", "underwear", "top", "skirt"]


# ----------------------------------------------------------------------
# through the pipeline: only where her own bottoms come off
# ----------------------------------------------------------------------
async def _run(orchestrator, store, source: bytes, prompt: str, *, adult: bool = False, **options):
    await store.put("sources/lined.vrm", source)
    payload = job_request("sources/lined.vrm", prompt, **options)
    payload["avatar"]["depictsAdult"] = adult
    return await orchestrator.run_now(CreateJobRequest.model_validate(payload))


async def test_a_clothed_avatar_gets_the_liner_where_her_bottoms_come_off(orchestrator, store, vrm_bytes):
    record = await _run(orchestrator, store, dress_like_vroid(vrm_bytes), "navy pleated mini skirt")
    assert record.state == "completed", record.error
    assert [g.role for g in record.plan.garments] == ["liner", "main"]
    assert record.plan.name == "Navy Pleated Mini Skirt" and record.look.name == record.plan.name
    assert "bottoms" in record.fit_report.replaced_garments
    assert any("under the skirt" in warning for warning in record.fit_report.warnings)


async def test_a_bare_body_or_her_own_bottoms_kept_gets_no_liner(orchestrator, store, vrm_bytes):
    bare = await _run(orchestrator, store, vrm_bytes, "navy pleated mini skirt")  # nothing of hers to replace
    kept = await _run(orchestrator, store, dress_like_vroid(vrm_bytes), "navy pleated mini skirt", replace_garments=False)
    for record in (bare, kept):
        assert record.state == "completed", record.error
        assert [g.role for g in record.plan.garments] == ["main"]
