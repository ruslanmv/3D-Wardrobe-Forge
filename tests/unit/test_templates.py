"""The shipped garment template library must stay valid."""

from __future__ import annotations

import json

import pytest

from wardrobe.domain.garments import CATEGORIES, COVERAGE_REGIONS, GarmentTemplate, TemplateCatalog
from wardrobe.vrm.skinning import bones_for_coverage


def test_catalog_loads(template_catalog: TemplateCatalog):
    assert len(template_catalog) >= 12


def test_every_template_is_semantically_valid(template_catalog: TemplateCatalog):
    assert template_catalog.validate_all() == []


def test_every_category_has_a_template(template_catalog: TemplateCatalog):
    covered = {template.category for template in template_catalog}
    assert covered == CATEGORIES


def test_template_ids_are_unique(template_catalog: TemplateCatalog):
    ids = [template.id for template in template_catalog]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("attribute", ["coverage", "anchors"])
def test_regions_are_known(template_catalog: TemplateCatalog, attribute: str):
    for template in template_catalog:
        unknown = set(getattr(template, attribute)) - COVERAGE_REGIONS
        assert not unknown, f"{template.id} declares unknown {attribute}: {unknown}"


def test_anchors_resolve_to_real_bones(template_catalog: TemplateCatalog):
    """A template whose anchors map to no bones could never be skinned."""
    for template in template_catalog:
        assert bones_for_coverage(template.anchors or template.coverage), template.id


def test_floor_length_garments_hang_from_the_hips(template_catalog: TemplateCatalog):
    """A long skirt covers the shins but must not be anchored to them.

    Binding a floor-length hem to the lower legs tears it apart the moment the
    legs swing in opposite directions; real long skirts hang from the pelvis.
    Garments with legs of their own — trousers, a catsuit — follow the legs.
    """
    for template in template_catalog:
        if template.hem not in {"floor", "ankle"} or template.category in {"trousers", "jumpsuit"}:
            continue
        assert "lowerLegs" not in template.anchors, (
            f"{template.id} is {template.hem}-length and anchored to lowerLegs"
        )


def test_clearance_is_sane(template_catalog: TemplateCatalog):
    for template in template_catalog:
        assert 0.0 <= template.fit.body_clearance_mm <= 40.0, template.id


def test_camel_case_json_round_trips():
    payload = {
        "schemaVersion": 1,
        "id": "test-v1",
        "name": "Test",
        "category": "dress",
        "mesh": "procedural:dress",
        "coverage": ["chest"],
        "anchors": ["chest"],
        "fit": {"bodyClearanceMm": 8.0, "allowLengthScale": False},
        "materials": {"supportsMetallic": True},
    }
    template = GarmentTemplate.model_validate(payload)
    assert template.fit.body_clearance_mm == 8.0
    assert template.fit.allow_length_scale is False
    assert template.materials.supports_metallic is True

    dumped = json.loads(template.model_dump_json(by_alias=True))
    assert dumped["fit"]["bodyClearanceMm"] == 8.0


def test_procedural_meshes_are_flagged(template_catalog: TemplateCatalog):
    for template in template_catalog:
        assert template.is_procedural, f"{template.id} references a binary mesh that is not shipped"
        assert template.procedural_kind
