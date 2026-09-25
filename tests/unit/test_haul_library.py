"""The try-on haul garment library: every template builds, routes and names itself."""

from __future__ import annotations

import pytest

from wardrobe.domain.garments import PROCEDURAL_KINDS, GarmentTemplate, TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.procedural import HAUL_KINDS, FitParameters, build_garment
from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ORIGINAL_KINDS = {"dress", "skirt", "top", "trousers", "jacket", "shoes"}


def test_the_domain_knows_every_shape_the_builder_makes():
    assert PROCEDURAL_KINDS == ORIGINAL_KINDS | HAUL_KINDS | LINGERIE_KINDS


def test_the_library_covers_the_haul_categories(template_catalog: TemplateCatalog):
    categories = {template.category for template in template_catalog.all()}
    assert {"swimwear", "underwear", "nightwear", "shorts", "legwear"} <= categories
    assert len(template_catalog.all()) >= 50


@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda body: body.name)
def test_every_template_builds_geometry_on_every_body(template_catalog: TemplateCatalog, body):
    document = GltfDocument.from_bytes(build_vrm(body, spec="VRM1"))
    measurements = measure_body(document, inspect_document(document))
    for template in template_catalog.all():
        params = FitParameters(
            measurements=measurements,
            sleeve_length=template.sleeve,
            metadata={"straps": template.fit.straps},
        )
        mesh = build_garment(template.procedural_kind, params, silhouette=template.silhouette, hem=template.hem)
        assert mesh.vertex_count > 0 and not mesh.validate(), template.id


def test_a_sleeved_template_without_arm_anchors_is_invalid(template_catalog: TemplateCatalog):
    """Sleeves bind to the anchored bones; chest-only anchors leave them out in a T when the arms drop."""
    good = template_catalog.get("top-crop-tee-v1")
    broken = GarmentTemplate.model_validate({**good.model_dump(by_alias=True), "anchors": ["chest"]})
    assert any("sleeves need anchors" in issue for issue in broken.validate_semantics())
    assert not good.validate_semantics()


def test_an_unknown_shape_is_invalid(template_catalog: TemplateCatalog):
    good = template_catalog.get("top-tube-v1")
    broken = GarmentTemplate.model_validate({**good.model_dump(by_alias=True), "mesh": "procedural:kimono"})
    assert any("unknown procedural shape" in issue for issue in broken.validate_semantics())


@pytest.mark.parametrize(
    ("prompt", "template_id"),
    [
        ("red triangle bikini", "swim-bikini-triangle-v1"),
        ("black bandeau bikini", "swim-bikini-bandeau-v1"),
        ("white one-piece swimsuit", "swim-one-piece-v1"),
        ("swimsuit with skirt", "swim-skirted-v1"),
        ("lace lingerie set", "under-lingerie-set-v1"),
        ("black lace bralette", "under-bralette-v1"),
        ("lace bodysuit", "under-bodysuit-v1"),
        ("satin nightgown", "night-nightgown-v1"),
        ("pajama bottoms", "night-pajama-trousers-v1"),
        ("pink crop top", "top-crop-tee-v1"),
        ("white tube top", "top-tube-v1"),
        ("halter top", "top-halter-v1"),
        ("cropped cardigan", "jacket-cropped-cardigan-v1"),
        ("lightweight trench", "jacket-trench-v1"),
        ("baggy jeans", "jeans-baggy-v1"),
        ("balloon trousers", "trousers-balloon-v1"),
        ("denim shorts", "shorts-denim-v1"),
        ("pleated mini skirt", "skirt-pleated-mini-v1"),
        ("tiered maxi skirt", "skirt-tiered-maxi-v1"),
        ("satin slip dress", "dress-slip-midi-v1"),
        ("maxi sundress", "dress-maxi-sundress-v1"),
        ("bodycon mini dress", "dress-mini-bodycon-v1"),
        ("thigh-high stockings", "legwear-thigh-highs-v1"),
    ],
)
def test_haul_prompts_route_to_their_template(template_catalog: TemplateCatalog, prompt, template_id):
    assert plan_outfit(OutfitRequest(prompt=prompt), template_catalog).template_id == template_id


def test_a_look_is_named_for_its_garment_not_its_category(template_catalog: TemplateCatalog):
    """A haul announces each look; "Red Swimwear" did not say which of four swimsuits."""
    assert plan_outfit(OutfitRequest(prompt="red triangle bikini"), template_catalog).name == "Red Triangle Bikini"
    assert plan_outfit(OutfitRequest(prompt="satin nightgown"), template_catalog).name == "Satin Nightgown"
    # The formal register is unchanged.
    assert plan_outfit(OutfitRequest(prompt="elegant burgundy evening dress"), template_catalog).name == (
        "Burgundy Evening"
    )
