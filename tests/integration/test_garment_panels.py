"""G6/G5. Garments cut as panels on her, not cylinders: the GC0 review's two outfits, by property.

"grey long cardigan + white fitted tee + black straight trousers" and "red cropped camisole +
black leggings" through the real pipeline on a calibration body, with what the panel builders
made captured on the way. Each assertion is a property the review found missing:

* the cardigan is open down the front, two fronts and a back, not a closed box;
* it is as long as its template says (knee), not cut at her hip;
* it covers her shoulders and has armholes, and its sleeves are sewn into them (one piece);
* below her seat it hangs, it does not follow her in;
* the camisole has a neckline, two flat straps, and ends above her navel;
* every piece is a clean surface: no holes but its openings, nothing non-manifold;
* the set-in sleeves are weighted from her skin, so the seam bends as she does (G5).
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.geometry import panels
from wardrobe.vrm import weight_transfer
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm

#: The builders as shipped: each job's capture wraps these, never another job's capture.
SET_IN, CAMISOLE_BUILDER, TRANSFER = panels.build_set_in_top, panels.build_camisole, weight_transfer.transfer_weights

CARDIGAN = "grey long cardigan + white fitted tee + black straight trousers"
CAMISOLE = "red cropped camisole + black leggings"


@pytest.fixture(scope="module")
def body() -> bytes:
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


async def _run(orchestrator, store, source: bytes, prompt: str, monkeypatch) -> dict:
    built: dict = {}
    bound: dict = {}
    set_in, camisole, transfer = SET_IN, CAMISOLE_BUILDER, TRANSFER

    def capture_set_in(params, style, **kw):
        mesh = set_in(params, style, **kw)
        built[style.name] = (params, mesh)
        return mesh

    def capture_camisole(params, **kw):
        pieces = camisole(params, **kw)
        built["camisole"] = (params, pieces)
        return pieces

    def capture_transfer(mesh, segments, *args, **kw):
        done = transfer(mesh, segments, *args, **kw)
        bound[mesh.metadata.get("section")] = (mesh, [s.name for s in segments], done)
        return done

    monkeypatch.setattr(panels, "build_set_in_top", capture_set_in)
    monkeypatch.setattr(panels, "build_camisole", capture_camisole)
    monkeypatch.setattr(weight_transfer, "transfer_weights", capture_transfer)
    await store.put("sources/panels.vrm", source)
    payload = job_request("sources/panels.vrm", prompt)
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    return {"record": record, "built": built, "bound": bound}


@pytest.fixture
async def cardigan_job(orchestrator, store, body, monkeypatch):
    return await _run(orchestrator, store, body, CARDIGAN, monkeypatch)


@pytest.fixture
async def camisole_job(orchestrator, store, body, monkeypatch):
    return await _run(orchestrator, store, body, CAMISOLE, monkeypatch)


def _boundary_loops(mesh) -> list[np.ndarray]:
    tris = mesh.indices.reshape(-1, 3).astype(int)
    edges = Counter()
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    assert max(edges.values()) <= 2, "an edge shared by more than two faces"
    adjacent = defaultdict(list)
    for (u, v), count in edges.items():
        if count == 1:
            adjacent[u].append(v)
            adjacent[v].append(u)
    seen, loops = set(), []
    for start in adjacent:
        if start in seen:
            continue
        stack, loop = [start], []
        while stack:
            vertex = stack.pop()
            if vertex not in seen:
                seen.add(vertex)
                loop.append(vertex)
                stack.extend(adjacent[vertex])
        loops.append(mesh.positions[loop])
    return loops


def _one_piece(mesh) -> bool:
    tris = mesh.indices.reshape(-1, 3).astype(int)
    parent = np.arange(mesh.vertex_count)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in tris:
        for u, v in ((a, b), (a, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv
    return len({find(i) for i in range(mesh.vertex_count)}) == 1


async def test_the_planned_outfits_are_the_ones_asked_for(cardigan_job, camisole_job):
    a, b = cardigan_job["record"], camisole_job["record"]
    assert [g.template_id for g in a.plan.garments] == [
        "top-fitted-tee-v1", "trousers-straight-v1", "jacket-long-cardigan-v1"]
    assert sorted(g.template_id for g in b.plan.garments) == ["top-cropped-cami-v1", "trousers-leggings-v1"]
    assert {g.template_id: g.material.color_name for g in b.plan.garments}["top-cropped-cami-v1"] == "red"
    for record in (a, b):
        assert record.fit_report.passed, record.fit_report.checks
        assert "requestedGarments" not in record.fit_report.checks


async def test_the_cardigan_is_two_open_fronts_and_a_back_to_the_knee(cardigan_job):
    params, mesh = cardigan_job["built"]["open-cardigan"]
    points = mesh.positions.astype(float)
    body = ~mesh.metadata["sleeve"]
    centre_x = float(np.median(points[body, 0]))
    front = (points[:, 2] - float(np.median(points[body, 2]))) * params.forward > 0

    # Open: nothing of it lies across her centre front, from the bust line to the hem.
    below_bust = points[:, 1] < params.chest_y
    across = front & below_bust & body & (np.abs(points[:, 0] - centre_x) < 0.03)
    assert not across.any(), "the cardigan closes across her front"
    # Its length is the template's, knee, not her hip.
    assert points[:, 1].min() < params.hip_y - 0.6 * (params.hip_y - params.knee_y)
    # It covers her shoulders: its yoke reaches her shoulder line.
    assert points[mesh.metadata["yoke"], 1].max() > params.shoulder_y
    # One piece: the sleeves are sewn into the armholes, not tubes beside a box.
    assert _one_piece(mesh)
    # Its openings and nothing else: front, neck and hem as one edge, and two cuffs.
    loops = _boundary_loops(mesh)
    assert len(loops) == 3, [len(loop) for loop in loops]


async def test_the_cardigan_hangs_from_her_seat_instead_of_following_her_in(cardigan_job):
    params, mesh = cardigan_job["built"]["open-cardigan"]
    points = mesh.positions.astype(float)
    body = ~mesh.metadata["sleeve"] & ~mesh.metadata["yoke"]
    cover = np.asarray(params.metadata["coverPoints"], dtype=float)

    def back(cloud, y):
        band = cloud[np.abs(cloud[:, 1] - y) < 0.012]
        return float((-band[:, 2] * params.forward).max())  # how far behind her axis, at this height

    seat, thigh = params.hip_y, params.hip_y - 0.5 * (params.hip_y - params.knee_y)
    her_drop = back(cover, seat) - back(cover, thigh)
    its_drop = back(points[body], seat) - back(points[body], thigh)
    assert her_drop > 0.02, "the calibration body has a seat to hang from"
    # Below her seat she comes in; the cardigan, hanging from it, comes in no more than a knit's
    # taper over that drop (wardrobe.geometry.panels.CARDIGAN), not with her. A bodice shell
    # followed her in: its back was a tube round her thighs.
    assert its_drop < her_drop * 0.4, (its_drop, her_drop)
    assert its_drop <= panels.CARDIGAN.taper * (seat - thigh) + 0.004


async def test_the_fitted_tee_is_one_closed_piece_with_its_four_openings(cardigan_job):
    _, mesh = cardigan_job["built"]["tee"]
    assert _one_piece(mesh)
    assert len(_boundary_loops(mesh)) == 4  # neck, hem, two sleeves


async def test_set_in_sleeves_take_her_skin_weights_across_the_armhole(cardigan_job):
    for name in ("open-cardigan", "tee"):
        mesh, bones, done = cardigan_job["bound"][name]
        assert done, f"{name} was not rebound from her skin"
        arm = np.array(["Arm" in bone for bone in bones])
        joints, weights = mesh.joints.astype(int), mesh.weights.astype(float)
        on_arm = (weights * arm[joints]).sum(axis=1)
        sleeve, yoke = mesh.metadata["sleeve"], mesh.metadata["yoke"]
        # The sleeve follows her arm; her shoulder is shared between arm and chest, and so is the
        # yoke beside the armhole: no hinge where one piece's weights stop and the other's start.
        assert np.median(on_arm[sleeve]) > 0.6
        assert ((on_arm[yoke] > 0.05) & (on_arm[yoke] < 0.95)).any()
        assert np.allclose(weights.sum(axis=1), 1.0, atol=1e-4)


async def test_the_camisole_has_a_neckline_flat_straps_and_a_cropped_hem(camisole_job):
    params, pieces = camisole_job["built"]["camisole"]
    body, *straps = pieces
    assert len(straps) == 2
    points = body.positions.astype(float)
    # Cropped: above her navel (her waist bone), and a top edge that is not one height round her.
    assert points[:, 1].min() > params.waist_y
    loops = sorted(_boundary_loops(body), key=lambda loop: loop[:, 1].mean())
    assert len(loops) == 2  # hem and top edge: a band with straps, not a closed tube
    top = loops[-1]
    assert np.ptp(top[:, 1]) > 0.015, "the top edge is cut flat round her"
    for strap in straps:
        p = strap.positions.astype(float)
        # A ribbon, not a cord: across her shoulder it is several times wider than it is thick.
        over = p[p[:, 1] > p[:, 1].max() - 0.004]
        assert np.ptp(over[:, 0]) > 4 * np.ptp(over[:, 1])
        assert p[:, 1].max() > params.shoulder_y  # over her shoulder
    assert body.metadata["panelBuilt"]


def test_without_her_measurements_a_panel_kind_still_builds_its_old_shape():
    from wardrobe.geometry.procedural import FitParameters, build_garment
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body

    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    params = FitParameters(measurements=measure_body(document, inspect_document(document)), sleeve_length="long")
    for kind in ("open-cardigan", "camisole", "tee"):
        mesh = build_garment(kind, params, hem="knee")
        assert mesh.vertex_count > 0 and not mesh.metadata.get("panelBuilt"), kind
