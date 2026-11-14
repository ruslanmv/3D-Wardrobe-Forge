"""AA. A missing adult garment is a card when a shell can cut it, and unbuilt when it cannot."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.atelier.orders import ORDERS, built_orders
from wardrobe.cloth.asset import compile_cloth_asset
from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.boots import build_boots, spec_for
from wardrobe.geometry.mesh import section_ranges
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
        # Gallery look 19 already says this. It stays the skater.
        ("red sheer mini dress", "dress-mini-skater-v1"),
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


def _section_points(mesh, needle: str) -> np.ndarray:
    tris = mesh.indices.reshape(-1, 3)
    chosen = []
    for name, first, count in section_ranges(mesh):
        if needle in name:
            chosen.append(mesh.positions[np.unique(tris[first:first + count])])
    assert chosen, needle
    return np.vstack(chosen)


def test_a_pump_on_a_shin_grows_a_needle_that_meets_the_floor():
    """VQ. The review mannequin has no foot. After the stance, the pump mesh has a needle."""
    from wardrobe.vrm import stance

    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[2], spec="VRM1"))
    info = inspect_document(document)
    target = stance.stance_for(document, info, heel_m=0.100, platform_m=0.004, forward=1.0)
    assert target is not None and target.pitch_deg > 0
    stance.apply(document, info, target, forward=1.0)
    posed = measure_body(document, inspect_document(document))

    def stump(side: str) -> np.ndarray:
        ankle = np.asarray(posed.bone_positions[f"{side}Foot"], dtype=np.float64)
        cloud = []
        for y in np.linspace(-0.01, 0.10, 8):
            for angle in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False):
                cloud.append(ankle + np.array([0.03 * np.cos(angle), y, 0.02 * np.sin(angle)]))
        return np.array(cloud)

    boot = build_boots(FitParameters(
        measurements=posed,
        metadata={"boot": {"style": "pump", "heelMm": 100, "platformMm": 4},
                  "bootBody": {"left": stump("left"), "right": stump("right")}},
    ))[0]
    assert float(boot.positions[:, 1].min()) >= -0.001
    heel = _section_points(boot, "heel")
    height = float(heel[:, 1].max() - heel[:, 1].min())
    assert height > 0.04
    tip = heel[heel[:, 1] < float(heel[:, 1].min()) + 0.012]
    assert float(tip[:, 0].max() - tip[:, 0].min()) < 0.025
    ankle_z = float(posed.bone_positions["leftFoot"][2])
    assert float(boot.positions[:, 2].max() - ankle_z) > 0.08


def test_a_missing_foot_keeps_the_measured_leg(measurements):
    """The synthetic foot is only the foot. A tall shaft still follows the calf that was measured."""
    ankle = np.asarray(measurements.bone_positions["leftFoot"], dtype=np.float64)
    knee = np.asarray(measurements.bone_positions["leftLowerLeg"], dtype=np.float64)

    def leg(side: str) -> np.ndarray:
        start = np.asarray(measurements.bone_positions[f"{side}Foot"], dtype=np.float64)
        end = np.asarray(measurements.bone_positions[f"{side}LowerLeg"], dtype=np.float64)
        cloud = []
        for t in np.linspace(0.0, 1.0, 14):
            centre = start + (end - start) * t
            radius = 0.035 + 0.032 * t
            for angle in np.linspace(0.0, 2.0 * np.pi, 14, endpoint=False):
                cloud.append(centre + np.array([radius * np.cos(angle), 0.0, 0.015 * np.sin(angle)]))
        return np.array(cloud)

    parts = build_boots(FitParameters(
        measurements=measurements,
        metadata={"boot": {"style": "over-knee"},
                  "bootBody": {"left": leg("left"), "right": leg("right")}},
    ))
    positions = np.vstack([part.positions for part in parts])
    band = positions[np.abs(positions[:, 1] - float(knee[1])) < 0.025]
    band = band[np.abs(band[:, 0] - float(ankle[0])) < 0.12]
    half = float(band[:, 0].max() - band[:, 0].min()) / 2.0
    assert half > 0.055


def test_fishnet_sleeves_stand_off_the_arm(measurements):
    profile = {"stations": [0.0, 0.45, 1.0, 1.45, 1.9],
               "left": [0.04, 0.035, 0.032, 0.028, 0.024],
               "right": [0.04, 0.035, 0.032, 0.028, 0.024]}

    def built(pattern: str):
        return build_garment(
            "catsuit",
            FitParameters(measurements=measurements, sleeve_length="long",
                          metadata={"armProfile": profile, "pattern": pattern}),
            silhouette="slim", hem="ankle",
        )

    def off_the_arm(mesh) -> float:
        upper = np.asarray(measurements.bone_positions["leftUpperArm"], dtype=np.float64)
        lower = np.asarray(measurements.bone_positions["leftLowerArm"], dtype=np.float64)
        axis = lower - upper
        pts = mesh.positions[mesh.positions[:, 0] > float(upper[0]) + 0.04]
        along = (pts - upper) @ axis / max(float(axis @ axis), 1e-9)
        on_arm = pts[(along > 0.15) & (along < 0.85)]
        offset = on_arm - upper - np.outer((on_arm - upper) @ axis, axis) / max(float(axis @ axis), 1e-9)
        return float(np.percentile(np.linalg.norm(offset, axis=1), 90))

    plain, net = built("none"), built("fishnet")
    assert off_the_arm(net) > off_the_arm(plain) + 0.01


def test_hot_pants_are_not_denim(template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt="white hot pants"), template_catalog)
    assert plan.template_id == "shorts-booty-v1"
    assert plan.style.coverage == "micro"
