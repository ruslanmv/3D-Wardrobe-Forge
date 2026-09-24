"""Changing clothes: which worn slots a garment takes over, and nothing more."""

from __future__ import annotations

import pytest

from tests.vroid_support import dress_like_vroid
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garments import (
    KIND_REGIONS,
    SLOT_REGIONS,
    garment_material_name,
    remove_slots,
    slots_replaced_by,
    worn_garments,
)
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body


def worn(vrm_bytes: bytes, slots=("Tops", "Bottoms")):
    document = GltfDocument.from_bytes(dress_like_vroid(vrm_bytes, slots=slots))
    return document, worn_garments(document)


def test_vroid_slots_are_found_by_material_name(vrm_bytes):
    _, found = worn(vrm_bytes, ("Tops", "Bottoms", "Shoes"))
    assert sorted(g.slot for g in found) == ["bottoms", "shoes", "tops"]


def test_a_plain_body_wears_nothing_recognisable(vrm_bytes):
    assert worn_garments(GltfDocument.from_bytes(vrm_bytes)) == []


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("top", ["tops"]),
        ("crop-top", ["tops"]),
        ("bra", ["tops"]),
        ("skirt", ["bottoms"]),
        ("shorts", ["bottoms"]),
        ("briefs", ["bottoms"]),
        ("dress", ["tops", "bottoms"]),
        ("bikini", ["tops", "bottoms"]),
        ("one-piece", ["tops", "bottoms"]),
        ("jacket", []),
        ("cropped-jacket", []),
        ("legwear", []),
    ],
)
def test_each_shape_takes_over_exactly_its_slots(vrm_bytes, kind, expected):
    _, found = worn(vrm_bytes)
    assert slots_replaced_by(kind, found) == expected


def test_a_top_never_removes_a_one_piece(vrm_bytes):
    """Removing a dress to put on a top would leave the lower half bare with nothing there."""
    _, found = worn(vrm_bytes, ("Onepiece",))
    assert slots_replaced_by("top", found) == []
    assert slots_replaced_by("skirt", found) == []
    assert slots_replaced_by("dress", found) == ["onepiece"]


def test_every_region_a_shape_claims_is_one_a_slot_can_occupy():
    regions = set().union(*SLOT_REGIONS.values())
    for kind, claimed in KIND_REGIONS.items():
        assert claimed <= regions, kind


def test_removal_drops_the_slot_and_keeps_the_body(vrm_bytes):
    document, _ = worn(vrm_bytes)
    removed = remove_slots(document, ["bottoms"])
    assert removed == ["F00_000_01_Bottoms_01_CLOTH"]
    remaining = [g.slot for g in worn_garments(document)]
    assert remaining == ["tops"]
    assert document.meshes[0]["primitives"][0]["material"] == 0  # the body is untouched


def test_a_slot_that_is_a_whole_mesh_is_taken_off_its_node(vrm_bytes):
    """A generated garment is its own mesh; emptying it would be invalid, so it is detached."""
    document = GltfDocument.from_bytes(dress_like_vroid(vrm_bytes, slots=("Tops",)))
    body = document.meshes[0]
    cloth = body["primitives"].pop()
    garment_mesh = document.add_mesh([cloth], "Red Crop Top")
    document.add_node({"name": "Red Crop Top", "mesh": garment_mesh})

    remove_slots(document, ["tops"])
    assert document.meshes[garment_mesh]["primitives"]  # still a valid mesh
    assert not any(node.get("mesh") == garment_mesh for node in document.nodes)
    assert worn_garments(document) == []  # taken off means no longer worn


def test_measurements_after_removal_describe_the_bare_body(vrm_bytes):
    """Depth comes from the bounding box; a removed slot must stop contributing to it."""
    document, _ = worn(vrm_bytes)
    info = inspect_document(document)
    clothed = measure_body(document, info)
    remove_slots(document, ["tops", "bottoms"])
    bare = measure_body(document, info)
    assert bare.depth_m <= clothed.depth_m
    assert bare.height_m == pytest.approx(clothed.height_m)


@pytest.mark.parametrize(
    ("kind", "marker"),
    [("crop-top", "Tops"), ("skirt", "Bottoms"), ("dress", "Onepiece"), ("bikini", "Onepiece"), ("shoes", "Shoes")],
)
def test_a_generated_garment_is_marked_so_the_next_one_can_replace_it(vrm_bytes, kind, marker):
    name = garment_material_name("Red Look", kind)
    assert name.startswith("Red Look") and f"_{marker}_01_CLOTH" in name
    document = GltfDocument.from_bytes(vrm_bytes)
    document.add_material({"name": name})
    body = document.meshes[0]
    body["primitives"].append({**body["primitives"][0], "material": len(document.materials) - 1})
    assert [g.slot for g in worn_garments(document)] == [marker.lower()]


def test_layers_carry_no_marker_and_are_never_replaced():
    assert garment_material_name("Tan Trench", "jacket") == "Tan Trench"
    assert garment_material_name("Thigh-Highs", "legwear") == "Thigh-Highs"
