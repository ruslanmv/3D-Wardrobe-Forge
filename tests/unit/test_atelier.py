"""AA. A missing adult garment is a card when a shell can cut it, and unbuilt when it cannot."""

from __future__ import annotations

import pytest

from wardrobe.atelier.orders import ORDERS, built_orders
from wardrobe.cloth.asset import compile_cloth_asset
from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.boots import build_boots, spec_for
from wardrobe.geometry.procedural import FitParameters, build_garment, front_angle
from wardrobe.pipeline.outfit_dictionary import OUTFITS, catalogue
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

BUILT = built_orders()


def _at(plan, path: str):
    obj = plan
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


@pytest.fixture(scope="module")
def planned(template_catalog):
    return {entry["id"]: entry for entry in catalogue(template_catalog)["outfits"]}


def test_the_book_is_on_the_outfits_payload_and_names_every_status(template_catalog):
    book = catalogue(template_catalog)["atelier"]
    assert book["version"] == 1
    assert {order.status for order in ORDERS} == {"built", "queued", "already", "shape"}
    assert [row["id"] for row in book["built"]] == [order.id for order in BUILT]
    assert {row["outfit"] for row in book["queued"]} <= {outfit.id for outfit in OUTFITS}
    assert book["unbuilt"] and all(row["why"] for row in book["unbuilt"])
    assert all("template" not in row for row in book["unbuilt"])


@pytest.mark.parametrize("order", BUILT, ids=lambda order: order.id)
def test_a_card_is_opt_in_and_the_prompt_selects_it(template_catalog, order, planned):
    template = template_catalog.get(order.template_id)
    assert template is not None and template.opt_in, order.id
    assert template.requires_adult is order.adult_card
    entry = planned[order.id]
    assert order.template_id in [g["template"] for g in entry["garments"]]
    plan = plan_outfit(OutfitRequest(prompt=order.prompt), template_catalog)
    assert plan.template_id == order.template_id


@pytest.mark.parametrize("order", [order for order in BUILT if order.baked], ids=lambda order: order.id)
def test_a_card_keeps_its_cut_when_the_prompt_is_only_a_colour(template_catalog, order):
    """Picking the card and a colour must not drop the plunge, the slit or the vinyl."""
    plan = plan_outfit(
        OutfitRequest(prompt="navy", template_id=order.template_id), template_catalog
    )
    for path, expected in order.baked:
        got = _at(plan, path)
        if isinstance(expected, float):
            assert got == pytest.approx(expected), (order.id, path)
        else:
            assert got == expected, (order.id, path, got)


@pytest.mark.parametrize(
    ("prompt", "template_id"),
    [
        ("red micro bikini", "swim-bikini-triangle-v1"),
        ("red backless dress", "dress-a-line-v1"),
        ("black bustier", "top-corset-v1"),
        ("black teddy", "under-bodysuit-v2"),
        ("black latex catsuit", "jumpsuit-catsuit-v1"),
        ("blue denim shorts", "shorts-denim-v1"),
        ("black monokini", "swim-one-piece-v1"),
        ("black high-cut one-piece swimsuit", "swim-one-piece-v2"),
        ("black stiletto boots", "shoes-stiletto-ankle-boots-v1"),
        ("black platform boots", "shoes-platform-boots-v1"),
        ("black fishnet catsuit", "jumpsuit-catsuit-v1"),
        ("black strappy sandals", "shoes-flats-v1"),
    ],
)
def test_words_that_already_meant_something_still_do(template_catalog, prompt, template_id):
    assert plan_outfit(OutfitRequest(prompt=prompt), template_catalog).template_id == template_id


def test_kimono_is_the_short_robe_and_sandals_are_not_pumps(template_catalog):
    robe = plan_outfit(OutfitRequest(prompt="black kimono"), template_catalog)
    assert robe.template_id == "night-short-robe-v1"
    sandals = plan_outfit(OutfitRequest(prompt="black strappy sandals"), template_catalog)
    assert sandals.template_id != "shoes-stiletto-pumps-v1"


def test_the_cut_out_monokini_is_open_at_the_waist(template_catalog):
    block = template_catalog.get("swim-cutout-monokini-v1").lingerie
    assert block["bodysuit"]["cutouts"] == "waist-sides"
    assert block["brief"]["preset"] == "high-leg"


def test_the_high_leg_is_a_french_cut(template_catalog):
    assert template_catalog.get("swim-high-leg-v1").lingerie["brief"]["preset"] == "french-cut"


def test_queued_looks_are_real_dictionary_entries():
    ids = {outfit.id for outfit in OUTFITS}
    queued = [order for order in ORDERS if order.status == "queued"]
    assert queued and all(order.outfit_id in ids for order in queued)


@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def test_the_slit_card_opens_one_thigh_and_is_a_cloth_asset(template_catalog, measurements):
    template = template_catalog.get("dress-slit-gown-v1")
    slit = FitParameters(measurements=measurements, metadata={"slit": template.fit.slit})
    plain = FitParameters(measurements=measurements, metadata={})
    cut = build_garment("dress", slit, silhouette="sheath", hem="floor")
    gown = build_garment("dress", plain, silhouette="sheath", hem="floor")
    angle = 0.5 if slit.forward >= 0 else -0.5

    def lowest(mesh, params, at):
        phi = front_angle(mesh.positions, params)
        near = abs((phi - at + 3.1416) % 6.2832 - 3.1416) < 0.12
        return float(mesh.positions[near, 1].min())

    assert lowest(cut, slit, angle) > lowest(gown, plain, angle) + 0.2
    asset = compile_cloth_asset(cut, kind="dress", silhouette="sheath", name="Thigh-Slit Gown")
    assert asset.profile == "cloth"


def test_a_micro_mini_is_shorter_than_a_mini_and_hot_pants_shorter_than_denim(measurements):
    plain = FitParameters(measurements=measurements, metadata={})
    micro = FitParameters(measurements=measurements, metadata={"coverage": "micro"})
    skirt = build_garment("skirt", plain, silhouette="pencil", hem="mini")
    shorter = build_garment("skirt", micro, silhouette="pencil", hem="mini")
    assert float(shorter.positions[:, 1].min()) > float(skirt.positions[:, 1].min()) + 0.02
    denim = build_garment("shorts", plain, silhouette="slim", hem="mini")
    hot = build_garment("shorts", micro, silhouette="slim", hem="mini")
    assert float(hot.positions[:, 1].min()) > float(denim.positions[:, 1].min()) + 0.02


def test_a_pump_ends_at_the_ankle_and_a_platform_heel_is_a_platform(measurements, template_catalog):
    def built(boot):
        meshes = build_boots(FitParameters(measurements=measurements, metadata={"boot": boot}))
        return meshes[0]

    pump = built({"style": "pump", "heelMm": 100, "platformMm": 4})
    ankle = built({"style": "stiletto-ankle", "heelMm": 95, "platformMm": 6})
    heel = built({"style": "platform-heel", "heelMm": 120, "platformMm": 40})
    pump_top = pump.metadata["bootMeasure"]["left"]["shaftTopMm"]
    ankle_top = ankle.metadata["bootMeasure"]["left"]["shaftTopMm"]
    heel_top = heel.metadata["bootMeasure"]["left"]["shaftTopMm"]
    assert pump_top < ankle_top - 40
    assert heel_top < ankle_top - 40
    # The 40 mm is the stance (set_stance reads boot.platformMm). Under a flat
    # foot the worn sole is clamped, the same as the platform boot, so the
    # mesh records the platform as its own piece rather than as a box she stands in.
    names = [name for name, _first, _count in heel.metadata["sections"]]
    assert any("platform" in name for name in names)
    assert not any("platform" in name for name, _a, _b in pump.metadata["sections"])
    asked = spec_for({"boot": template_catalog.get("shoes-platform-heels-v1").boot})
    assert asked["sole"] == "platform" and asked["platformMm"] == 40 and asked["shaft"] == "pump"


def test_hot_pants_are_not_denim(template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt="white hot pants"), template_catalog)
    assert plan.template_id == "shorts-booty-v1"
    assert plan.style.coverage == "micro"
