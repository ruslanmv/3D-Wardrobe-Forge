"""BR2. The BC1 patch that completes a deleted chest, measured where it meets her.

Each test pins one defect measured on the deleted-chest fixture (``tests/body_completion_support``)
before the change, with the number it had:

* the patch stopped half a 1 cm row short of her rim: her rim 3.1 mm from it on average, 5.5 mm
  at worst — a crack all round;
* its normals pointed level out of her axis: 25° from hers at the seam;
* it took the weights of the garment over the hole: with the top rigged like cloth, 1.68 (of 2)
  weight difference at the seam, and her rim 33.5 mm from the patch with her arms down;
* its material was forced OPAQUE where hers is MASK;
* the patch was added to her own skin mesh, and her mesh was tagged ``bodyProxy``.

And one that is not the patch: VRoid's ``…_Onepiece_00_CLOTH_01`` sub-parts were not clothing,
so AvatarSample_O's collar and cuff stayed on a bare build of her.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.body_completion_support import complete_bare, deleted_chest, rig_top_like_cloth
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.completion_join import closest_on_triangles, measure_join
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.skin_restore import KNOWN_DISTANCE

SAMPLE_O = Path(__file__).resolve().parents[2] / "assets" / "library" / "vroid" / "vroid-avatar-sample-o.vrm"
BARE = {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"}


def _completed(cloth: bool):
    document = deleted_chest()
    if cloth:
        document = rig_top_like_cloth(document)
    before = [len(m["primitives"]) for m in document.meshes]
    run = complete_bare(document)
    return document, run, before, measure_join(document, run["measurements"], run["info"])


@pytest.fixture(scope="module")
def completed():
    return _completed(cloth=False)


@pytest.fixture(scope="module")
def cloth_rigged():
    return _completed(cloth=True)


def test_the_fixture_has_a_hole_and_the_patch_closes_it(completed):
    document, run, _, join = completed
    completion = run["completion"]
    assert completion["regions"] == ["upper"] and completion["applied"]
    assert check_body(document, run["measurements"], BARE, bare=True).complete
    assert join["rimVertices"] > 50


def test_the_patch_reaches_her_rim(completed):
    gap = completed[3]["gapMm"]
    # Beneath her rim by about UNDER_SKIN_M (1.5 mm), never half a row short of it (was 3.1 / 5.5).
    assert gap["mean"] < 2.0, gap
    assert gap["max"] < 4.0, gap


def test_the_patch_is_never_in_front_of_her_skin_or_at_its_depth(completed):
    overlap = completed[3]["overlap"]
    assert overlap["zFightVertices"] == 0, overlap
    assert overlap["inFrontOfSkinVertices"] == 0, overlap


def test_the_shading_runs_on_across_the_seam(completed):
    normals = completed[3]["normals"]
    assert normals["seamDeg"]["max"] < 10.0, normals  # was 25.3


def test_the_patch_moves_with_her_skin_not_with_the_garment(cloth_rigged):
    _, run, _, join = cloth_rigged
    assert run["completion"]["patch"]["weightsFrom"] == "skin"
    assert join["weights"]["seamL1"]["max"] < 0.3, join["weights"]  # was 1.68
    for pose, numbers in join["posed"].items():
        assert numbers["gapMm"]["max"] < 10.0, (pose, numbers)  # arms-down was 33.5


def test_the_patch_is_her_colour_at_the_seam(completed):
    colour = completed[3]["colour"]["rgbDistance"]
    assert colour["max"] is not None and colour["max"] < KNOWN_DISTANCE, colour


def test_the_patch_is_a_mesh_of_its_own_in_her_render_state(completed):
    document, _, before, join = completed
    assert join["material"]["differs"] == []
    tags = join["tags"]
    assert tags["patchOnOwnMesh"] and tags["taggedIsPatch"], tags
    # Her own mesh: no tag, and no primitive added to it (the top came off, nothing went on).
    skin_mesh = document.meshes[0]
    assert "bodyProxy" not in ((skin_mesh.get("extras") or {}).get("wardrobeForge") or {})
    assert len(skin_mesh["primitives"]) == before[0] - 1
    node = next(n for n in document.nodes if n.get("name") == "Body proxy")
    assert node["extras"]["wardrobeForge"]["kind"] == "bodyProxy"
    assert node["skin"] == next(n for n in document.nodes if n.get("mesh") == 0)["skin"]


def test_closest_point_distance_matches_brute_force():
    rng = np.random.default_rng(7)
    triangles = rng.normal(size=(20, 3, 3))
    points = rng.normal(size=(40, 3)) * 2
    k = 120
    i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
    keep = i + j <= k
    u, v = i[keep] / k, j[keep] / k
    samples = np.einsum("sk,tkd->tsd", np.stack([1 - u - v, u, v], axis=1), triangles).reshape(-1, 3)
    brute = np.array([np.sqrt(((samples - p) ** 2).sum(axis=1)).min() for p in points])
    distance, _ = closest_on_triangles(points, triangles)
    assert (distance <= brute + 1e-9).all()
    assert np.abs(distance - brute).max() < 0.01


def test_vroid_outfit_sub_parts_are_clothing():
    from wardrobe.vrm.garment_inventory import _VROID

    assert _VROID.search("N00_010_01_Onepiece_00_CLOTH_01 (Instance)").group(1) == "Onepiece"
    assert _VROID.search("N00_002_03_Tops_01_CLOTH (Instance)").group(1) == "Tops"
    assert _VROID.search("N00_000_00_Body_00_SKIN (Instance)") is None
    assert _VROID.search("N00_010_01_Onepiece_00_CLOTHES") is None


@pytest.mark.skipif(not SAMPLE_O.exists(), reason="library AvatarSample_O unavailable")
def test_sample_o_collar_and_cuff_are_her_clothing():
    from wardrobe.vrm.document import GltfDocument

    found = {(g.slot, g.primitive) for g in garment_inventory(GltfDocument.from_path(SAMPLE_O))}
    assert found == {("shoes", 2), ("tops", 3), ("onepiece", 4), ("onepiece", 5)}


def test_the_review_packet_of_a_reconstructed_file_says_so_and_names_the_band(completed, tmp_path):
    import importlib.util

    from wardrobe.config import Settings
    from wardrobe.library import AvatarLibrary

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("review_packet", root / "tools/body_surface/review_packet.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    path = tmp_path / "reconstructed.vrm"
    path.write_bytes(completed[0].to_bytes())
    packet = tool.packet(path, slug=None, library=AvatarLibrary.from_directory(root / "assets" / "library"),
                         settings=Settings(_env_file=None))
    made = packet["reconstruction"]
    assert made["reconstructed"] and made["regions"] == ["upper"] and made["method"] == "bc1-proxy"
    assert made["patchMeshes"] == ["Body proxy"]
    text = tool.markdown(packet)
    assert "## This file is reconstructed" in text and "**upper**" in text
    assert all(value == "" for value in packet["reviewEntry"]["entry"].values())


@pytest.mark.skipif(not SAMPLE_O.exists(), reason="library AvatarSample_O unavailable")
def test_the_review_packet_of_her_source_file_says_nothing_was_made():
    import importlib.util

    from wardrobe.config import Settings
    from wardrobe.library import AvatarLibrary

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("review_packet", root / "tools/body_surface/review_packet.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    packet = tool.packet(SAMPLE_O, slug="vroid-avatar-sample-o",
                         library=AvatarLibrary.from_directory(root / "assets" / "library"),
                         settings=Settings(_env_file=None))
    assert packet["reconstruction"]["reconstructed"] is False
    assert "## This file is reconstructed" not in tool.markdown(packet)
