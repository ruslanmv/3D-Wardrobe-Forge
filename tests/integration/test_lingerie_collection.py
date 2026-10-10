"""LC1–LC4. The Italian lace collection: one bralette, a thong or a Brazilian, made and finished.

Each set is built once, through the real pipeline, on the fashion-fit form the
repository declares adult; every assertion reads the VRM that comes out.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import numpy as np
import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.lingerie import atelier, fabrics
from wardrobe.lingerie.collections import BOTTOM_STYLES, design
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.document import GltfDocument

ROOT = Path(__file__).resolve().parents[2]
FORM = "fit-form-a-misses"
#: The components the specification names, per piece.
BRA_PARTS = {"bra_left_cup", "bra_right_cup", "bra_underband", "bra_strap_L", "bra_strap_R", "bra_back_band",
             "bra_lace_L", "bra_lace_R", "hardware", "bow_center"}
BOTTOM_PARTS = {"bottom_front", "bottom_side_L", "bottom_side_R", "bottom_lace", "bow_L", "bow_R"}


def _build(style: str, *, declared: bool = True):
    from wardrobe.config import Settings
    from wardrobe.domain.jobs import CreateJobRequest
    from wardrobe.pipeline.orchestrator import Orchestrator
    from wardrobe.policy.calibration import declared_adult
    from wardrobe.queue.jobs import AsyncioJobQueue
    from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
    from wardrobe.storage.object_store import LocalObjectStore
    from wardrobe.vrm.fashion_body import build_fit_form, fit_form

    async def run(tmp: Path):
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                            catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
        await store.put("sources/form.vrm", build_fit_form(fit_form(FORM)))
        preset = f"italian_lace_{style}_set"
        record = await orch.run_now(CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/form.vrm", "avatarId": FORM,
                       "depictsAdult": declared_adult(FORM) if declared else False},
            "outfit": {"prompt": preset, "preset": preset},
            "options": {"renderPreview": False, "engine": "native"},
        }))
        data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
        return record, GltfDocument.from_bytes(data) if data else None

    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(run(Path(tmp)))


@pytest.fixture(scope="module")
def sets():
    return {style: _build(style) for style in BOTTOM_STYLES}


def _garments(document):
    out = {}
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") == "garment":
            out[(tag.get("collection") or {}).get("piece")] = (node, tag)
    return out


def _primitives(document, node):
    """{material name suffix: (positions of its vertices, material)} for a garment node."""
    out = {}
    for primitive in document.meshes[node["mesh"]]["primitives"]:
        material = document.materials[primitive["material"]]
        positions = document.read_accessor(primitive["attributes"]["POSITION"])[:, :3]
        used = np.unique(document.read_accessor(primitive["indices"]).reshape(-1))
        suffix = material["name"].split(" [")[0].split(" ")[-1]
        out[suffix] = (positions[used], material)
    return out


# ----------------------------------------------------------------------
# planning: the switch, and what it leaves alone
# ----------------------------------------------------------------------
@pytest.mark.parametrize("style", BOTTOM_STYLES)
def test_a_preset_plans_the_collections_two_pieces(template_catalog, style):
    plan = plan_outfit_stack(OutfitRequest(prompt=f"italian_lace_{style}_set", preset=f"italian_lace_{style}_set"),
                             template_catalog)
    pieces = {g.style.collection["piece"]: g for g in plan.garments if g.style.collection}
    assert set(pieces) == {"bra", "bottom"}
    assert pieces["bra"].template_id == "under-bralette-v2"
    assert pieces["bottom"].template_id == design("italian-lace", style)["bottom"]["template"]
    for piece in pieces.values():
        assert piece.requires_adult and piece.set_id == f"italian-lace-{style}"
        assert 0.15 <= piece.material.opacity <= 0.3 and piece.material.alpha_mode == "blend"


def test_the_switch_changes_the_bottom_and_never_the_bra():
    thong, brazilian = (design("italian-lace", s) for s in BOTTOM_STYLES)
    same = {k: v for k, v in thong["bra"].items() if k != "bottomStyle"}
    assert same == {k: v for k, v in brazilian["bra"].items() if k != "bottomStyle"}
    assert thong["bottom"]["template"] != brazilian["bottom"]["template"]


def test_nothing_changes_without_the_block(template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt="black tailored thong"), template_catalog)
    assert all(g.style.collection is None for g in plan.garments)


# ----------------------------------------------------------------------
# fabrics
# ----------------------------------------------------------------------
def _alpha(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3] / 255.0


def test_lace_and_mesh_are_different_fabrics():
    lace = _alpha(fabrics.galloon(30.0))
    assert lace[0].min() > 0.9                 # the straight edge sewn to the garment
    assert lace[-1].max() < 0.05 or lace[-2:].mean() < 0.2  # past the scallops, nothing
    assert 0.35 <= lace.mean() <= 0.7          # mostly motif and net, unlike the mesh
    mesh = _alpha(fabrics.dotted_mesh(0.3))
    assert abs(np.median(mesh) - 0.3) < 0.02   # the ground is the mesh's opacity
    assert mesh.max() > 0.9                    # the flock dots are near-opaque


def test_the_bow_and_charm_are_small_parts():
    bow = atelier.bow_local(0.02)
    extent = bow.positions.max(axis=0) - bow.positions.min(axis=0)
    assert extent[0] <= 0.025 and bow.triangle_count < 1500
    charm = atelier.charm_local()
    assert np.max(charm.positions.max(axis=0) - charm.positions.min(axis=0)) <= 0.013


# ----------------------------------------------------------------------
# through the pipeline
# ----------------------------------------------------------------------
@pytest.mark.parametrize("style", BOTTOM_STYLES)
def test_both_sets_are_made_and_fit(sets, style):
    record, document = sets[style]
    assert record.state.value == "completed", record.error
    assert record.fit_report.passed
    pieces = _garments(document)
    assert set(pieces) == {"bra", "bottom"}


@pytest.mark.parametrize("style", BOTTOM_STYLES)
def test_every_named_component_is_there(sets, style):
    _, document = sets[style]
    pieces = _garments(document)
    assert set(pieces["bra"][1]["components"]) >= BRA_PARTS
    bottom = set(pieces["bottom"][1]["components"])
    assert bottom >= BOTTOM_PARTS
    assert ("thong_back_strap" in bottom) == (style == "thong")
    assert ("bottom_back" in bottom) == (style == "brazilian")


def test_left_and_right_are_made_alike(sets):
    _, document = sets["brazilian"]
    components = _garments(document)["bra"][1]["components"]
    for part in ("bra_lace", "bra_binding", "bra_left_cup"):
        left = components.get(f"{part}_L", components.get(part))["triangles"]
        right = components.get(f"{part}_R", components.get("bra_right_cup"))["triangles"]
        # A band is resampled every 5 mm along its fitted edge: one sample either way is a
        # few millimetres of edge, not a different part.
        assert abs(left - right) <= max(0.03 * left, 16), (part, left, right)
    bottom = _garments(document)["bottom"][1]["components"]
    assert bottom["bow_L"]["triangles"] == bottom["bow_R"]["triangles"]


@pytest.mark.parametrize("style", BOTTOM_STYLES)
def test_each_fabric_is_its_own_material(sets, style):
    _, document = sets[style]
    for piece, (node, _) in _garments(document).items():
        primitives = _primitives(document, node)
        mesh = next(m for k, (_, m) in primitives.items() if k not in fabrics_suffixes())
        assert mesh.get("alphaMode") == "BLEND"
        assert {"Lace", "Satin", "Hardware", "Trim"} <= set(primitives) | ({"Hardware"} if piece == "bottom" and
                                                                           style == "brazilian" else set())
        lace = primitives["Lace"][1]
        assert lace.get("alphaMode") == "BLEND" and "baseColorTexture" in lace["pbrMetallicRoughness"]
        satin = primitives["Satin"][1]["pbrMetallicRoughness"]["baseColorFactor"]
        assert satin[0] > satin[2] > 0.2  # blush: pink, not black


def fabrics_suffixes():
    return {"Band", "Lining", "Trim", "Lace", "Satin", "Hardware"}


@pytest.mark.parametrize("style", BOTTOM_STYLES)
def test_the_lace_lies_on_the_fabric(sets, style):
    """Sewn on, not floating: lace within a few millimetres of the fabric's triangles under it."""
    _, document = sets[style]
    for node, _ in _garments(document).values():
        lace, triangles = _lace_and_fabric(document, node)
        a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
        centroid = triangles.mean(axis=1)
        gaps = []
        for start in range(0, lace.shape[0], 128):
            q = lace[start:start + 128]
            near = np.argsort(np.linalg.norm(q[:, None, :] - centroid[None, :, :], axis=2), axis=1)[:, :16]
            best = atelier._closest_on_triangles(q[:, None, :], a[near], b[near], c[near])
            gaps.append(np.min(np.linalg.norm(best - q[:, None, :], axis=2), axis=1))
        gaps = np.concatenate(gaps)
        assert np.percentile(gaps, 95) < 0.004, np.percentile(gaps, 95)


def _lace_and_fabric(document, node):
    """The lace's vertices, and the triangles of everything it can be sewn to (mesh, band, trim)."""
    lace, triangles = None, []
    for primitive in document.meshes[node["mesh"]]["primitives"]:
        # "Black Italian Lace Thong Lace [Forge_…]": the last word before the slot tag is the fabric.
        name = document.materials[primitive["material"]]["name"].split(" [")[0].split(" ")[-1]
        positions = document.read_accessor(primitive["attributes"]["POSITION"])[:, :3].astype(np.float64)
        indices = document.read_accessor(primitive["indices"]).reshape(-1, 3)
        if name == "Lace":
            lace = positions[np.unique(indices)]
        elif name not in ("Satin", "Hardware"):
            triangles.append(positions[indices])
    return lace, np.concatenate(triangles)


def test_an_avatar_not_declared_adult_is_refused():
    record, _ = _build("thong", declared=False)
    assert record.state.value != "completed"
