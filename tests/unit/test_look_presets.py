"""P1. Two looks: a corset top over a low-rise mini, and a thong worn above low-rise jeans.

Both are shorthand for requests someone could type. The corset look is clothes and
needs no declaration; the visible thong is underwear and is refused, as any
underwear is, for an avatar nobody declared adult. What the looks add to the
geometry — a skirt's rise, a corset, a thong's waistline placed against the
jeans' — is pinned here, and the pipeline runs on the calibration mannequin,
which the repository's own policy file declares adult.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.errors import PlanningError
from wardrobe.geometry.procedural import FitParameters, build_garment, crotch_y, skirt_top
from wardrobe.pipeline import look_presets
from wardrobe.pipeline.plan_outfit import parse_prompt
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> TemplateCatalog:
    return TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")


def plan(catalog, **request):
    return plan_outfit_stack(OutfitRequest.model_validate(request), catalog)


# ----------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------
def test_the_corset_look_is_a_corset_over_a_low_rise_mini(catalog):
    garments = plan(catalog, prompt="corset_top_low_rise_mini", preset="corset_top_low_rise_mini").garments
    assert [g.template_id for g in garments] == ["top-corset-v1", "skirt-pleated-mini-v1"]
    assert garments[1].style.rise == "low"
    assert not any(g.category == "underwear" for g in garments)  # clothes: nothing to declare


@pytest.mark.parametrize("style", sorted(look_presets.VISIBLE_THONG_STYLES))
def test_the_visible_thong_block_moves_two_waistlines_and_nothing_else(catalog, style):
    garments = plan(catalog, prompt="visible_thong_low_rise_jeans", preset="visible_thong_low_rise_jeans",
                    visibleThong={"style": style}).garments
    by_id = {g.template_id: g for g in garments}
    thong_rise, jeans_rise = look_presets.VISIBLE_THONG_STYLES[style]
    assert by_id["under-v-string-v2"].style.brief_rise == thong_rise
    assert by_id["under-v-string-v2"].category == "underwear"  # gated as underwear, whatever the style
    assert by_id["jeans-straight-v1"].style.rise == jeans_rise
    assert by_id["top-crop-tee-v1"].style.brief_rise is None and by_id["top-crop-tee-v1"].style.rise == ""


def test_the_cami_version_is_a_plain_cropped_cami_over_baggy_low_rise_jeans(catalog):
    outfit = plan(catalog, prompt="visible_thong_cami_baggy_jeans", preset="visible_thong_cami_baggy_jeans")
    by_id = {g.template_id: g for g in outfit.garments}
    assert set(by_id) == {"under-v-string-v2", "top-cropped-cami-v1", "jeans-baggy-v1"}
    assert all(g.material.color_name == ("blue" if g.category == "trousers" else "white") for g in outfit.garments)
    assert "Lace" not in outfit.name  # a plain cami, not the lace one
    assert by_id["under-v-string-v2"].style.brief_rise == look_presets.VISIBLE_THONG_STYLES["classic"][0]
    assert by_id["jeans-baggy-v1"].style.rise == "low"


def test_the_plain_cami_is_chosen_only_by_name(catalog):
    from wardrobe.pipeline.plan_outfit import select_template

    for prompt, template in (("white crop cami", "top-crop-cami-v1"), ("lace crop cami", "top-crop-cami-v1"),
                             ("white cropped cami", "top-cropped-cami-v1")):
        assert select_template(catalog, parse_prompt(prompt), prompt).id == template


def test_explicit_rises_win_over_the_style(catalog):
    garments = plan(catalog, prompt="visible_thong_low_rise_jeans", preset="visible_thong_low_rise_jeans",
                    visibleThong={"style": "subtle", "thongRise": 1.1, "jeansRise": "ultra-low"}).garments
    by_id = {g.template_id: g for g in garments}
    assert by_id["under-v-string-v2"].style.brief_rise == 1.1
    assert by_id["jeans-straight-v1"].style.rise == "ultra-low"


def test_the_block_without_a_thong_or_trousers_says_so_and_changes_nothing(catalog):
    outfit = plan(catalog, prompt="blue straight jeans + white fitted crop top", visibleThong={"style": "classic"})
    assert "visible thong: the outfit has no thong" in outfit.notes
    assert all(g.style.brief_rise is None for g in outfit.garments)


def test_a_preset_is_only_shorthand(catalog):
    typed = plan(catalog, prompt="black corset top + black low-rise pleated mini skirt").garments
    named = plan(catalog, prompt="corset_top_low_rise_mini", preset="corset_top_low_rise_mini").garments
    assert [(g.template_id, g.style) for g in typed] == [(g.template_id, g.style) for g in named]
    # A request's own prompt is kept: the preset fills only what was left empty.
    own = plan(catalog, prompt="red corset top + black low-rise pleated mini skirt", preset="corset_top_low_rise_mini")
    assert own.garments[0].material.color_name == "red"


def test_hosiery_presets_and_unknown_names_are_as_before(catalog):
    assert plan(catalog, prompt="glimpse_black", preset="glimpse_black").garments
    with pytest.raises(PlanningError, match="unknown hosiery preset"):
        plan(catalog, prompt="whatever", preset="no_such_look")


def test_corset_words_name_the_corset_and_the_foundations_keep_theirs(catalog):
    from wardrobe.pipeline.plan_outfit import select_template

    for prompt, template in (("black satin bustier", "top-corset-v1"), ("corset", "top-corset-v1"),
                             ("black lace guepiere", "under-guepiere-v1"), ("black waspie", "under-waspie-v1")):
        assert select_template(catalog, parse_prompt(prompt), prompt).id == template
    assert parse_prompt("super low-rise jeans").rise == "ultra-low"
    assert parse_prompt("low-rise jeans").rise == "low"


# ----------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def body():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def test_a_skirt_starts_at_her_waist_unless_it_is_low_rise(body):
    params = FitParameters(measurements=body)
    assert skirt_top(params) == params.waist_y
    low = skirt_top(FitParameters(measurements=body, metadata={"rise": "low"}))
    ultra = skirt_top(FitParameters(measurements=body, metadata={"rise": "ultra-low"}))
    assert params.hip_y < ultra < low < params.waist_y
    assert ultra > crotch_y(params, params.hip_y) + 0.05


def test_a_corset_reaches_her_waist_and_points_at_the_front(body):
    params = FitParameters(measurements=body, metadata={"neckline": "sweetheart"})
    mesh = build_garment("corset", params)
    p = mesh.positions
    assert mesh.metadata.get("boningPitchM")
    front = p[np.abs(p[:, 0]) < 0.01]
    side = p[np.abs(p[:, 0]) > np.abs(p[:, 0]).max() * 0.85]
    assert front[:, 1].min() < side[:, 1].min() - 0.02  # the centre-front point
    assert abs(side[:, 1].min() - params.waist_y) < 0.03  # a corset is to the waist, not the underbust


def test_a_brief_rise_placed_by_a_look_raises_the_waistline(body):
    from wardrobe.lingerie.blocks import build_block

    template = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates").get("under-v-string-v2")
    base = {"lingerie": dict(template.lingerie)}
    heights = [float(build_block("brief-block", FitParameters(measurements=body, metadata=meta)).positions[:, 1].max())
               for meta in (base, {**base, "briefRise": 1.05})]
    assert heights[1] > heights[0] + 0.02


# ----------------------------------------------------------------------
# through the pipeline, on the mannequin the repository declares adult
# ----------------------------------------------------------------------
def _dress(outfit: dict, *, declared: bool):
    sys.path.insert(0, str(ROOT / "tools" / "gallery"))
    from looks import dressed_mannequin

    from wardrobe.config import Settings
    from wardrobe.domain.jobs import CreateJobRequest
    from wardrobe.pipeline.orchestrator import Orchestrator
    from wardrobe.policy.calibration import declared_adult
    from wardrobe.queue.jobs import AsyncioJobQueue
    from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
    from wardrobe.storage.object_store import LocalObjectStore

    async def run(tmp: Path):
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                            catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
        await store.put("sources/m.vrm", dressed_mannequin())
        adult = declared_adult("calibration-c-tall") if declared else False
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/m.vrm", "avatarId": "mannequin", "depictsAdult": adult},
            "outfit": {"mode": "template", **outfit}, "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orch.run_now(request)
        data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
        return record, GltfDocument.from_bytes(data) if data else None

    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(run(Path(tmp)))


def _points(document, prefix):
    out = []
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if (tag.get("templateId") or "").startswith(prefix) and "mesh" in node:
            for primitive in document.meshes[node["mesh"]]["primitives"]:
                p = document.read_accessor(primitive["attributes"]["POSITION"])[:, :3]
                out.append(p[np.unique(document.read_accessor(primitive["indices"]).reshape(-1))])
    return np.vstack(out)


def test_the_whale_tail_shows_the_thong_above_the_jeans():
    record, document = _dress({"prompt": "visible_thong_low_rise_jeans", "preset": "visible_thong_low_rise_jeans"},
                              declared=True)
    assert record.fit_report.passed
    thong, jeans = _points(document, "under-v-string"), _points(document, "jeans-")
    straps = thong[np.abs(thong[:, 0]) > 0.07][:, 1].max() - jeans[:, 1].max()
    assert 0.03 < straps < 0.08  # classic: ~5 cm of strap above the waistband


def test_an_undeclared_avatar_is_refused_the_thong_and_given_the_corset():
    record, _ = _dress({"prompt": "visible_thong_low_rise_jeans", "preset": "visible_thong_low_rise_jeans"},
                       declared=False)
    assert record.look is None and "depictsAdult" in str(record.error)
    record, document = _dress({"prompt": "corset_top_low_rise_mini", "preset": "corset_top_low_rise_mini"},
                              declared=False)
    assert record.fit_report.passed
    skirt, liner = _points(document, "skirt-"), _points(document, "shorts-slip")
    assert liner[:, 1].max() < skirt[:, 1].max() - 0.01  # the liner stays under the low waistband
