"""KL3. The pass is measured inside one build, and a seam's two sides stay in one place.

``tools/inspect/kept_top_trace.py`` exists because the first measurement was wrong: a look was
compared with a second build of it made with the pass switched off, and a pair of vertices that
coincide in *that* build's shell and are 1.8 mm apart in this one's was reported as a seam the
pass had opened. These tests hold the measurement itself (it sees a seam that really parts, a
triangle that really turns), and then run it on a committed character who keeps a top of her
own: what shares a position before the pass shares one after it and in the exported file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
KEEPS_A_TOP = "vroid-avatar-sample-o"  # committed; no kept top over a Forge bottom here


@pytest.fixture(scope="module")
def tool():
    sys.path.insert(0, str(ROOT / "tools" / "inspect"))
    spec = importlib.util.spec_from_file_location("kept_top_trace", ROOT / "tools/inspect/kept_top_trace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strip():
    """Two quads side by side with a seam between them: vertices 1/4 and 2/5 share positions."""
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                       [1, 0, 0], [1, 1, 0], [2, 1, 0], [2, 0, 0]], dtype=float) * 0.01
    triangles = np.array([[0, 1, 2], [0, 2, 3], [4, 7, 6], [4, 6, 5]])
    return points, triangles


def test_pairs_are_vertices_that_share_a_position(tool):
    points, _ = _strip()
    assert sorted(map(tuple, tool.coincident_pairs(points).tolist())) == [(1, 4), (2, 5)]
    assert tool.coincident_pairs(points[:4]).shape == (0, 2)


def test_a_mesh_moved_as_one_piece_reads_as_intact(tool):
    points, triangles = _strip()
    moved = points + np.array([0.0, 0.0, 0.004])
    report = tool.measure(points, moved, triangles, exported=moved)
    assert report["seamPairs"] == 2 and report["seamGapAfterPassMm"] == 0.0 and report["seamGapExportedMm"] == 0.0
    assert report["edgeRatio"] == [1.0, 1.0] and report["edgesPast1_5x"] == 0 and report["flippedTriangles"] == 0
    assert report["movedVertices"] == 8 and report["maxMoveMm"] == 4.0 and report["heightChangedMm"] == 0.0
    assert report["exportedIsWhatThePassLeft"] is True


def test_a_seam_that_parts_a_stretched_edge_and_a_turned_triangle_are_all_seen(tool):
    points, triangles = _strip()
    after = points.copy()
    after[4] += [0.0, 0.0, 0.002]  # one side of the seam leaves the other
    after[6] = [0.035, 0.01, 0.0]  # an edge pulled long
    after[3] = [0.02, -0.01, 0.0]  # a corner dragged across its own triangle
    report = tool.measure(points, after, triangles, exported=points)
    assert report["seamGapAfterPassMm"] == 2.0
    assert report["edgesPast1_5x"] >= 1 and report["edgeRatio"][1] > 1.5
    assert report["flippedTriangles"] >= 1
    assert report["exportedIsWhatThePassLeft"] is False
    # An export with other vertices cannot be compared: said, not called a difference.
    assert tool.measure(points, after, triangles, exported=points[:5])["exportedIsWhatThePassLeft"] is None


@pytest.mark.skipif(not (ROOT / "assets" / "library" / "AvatarSample_C.vrm").is_file(),
                    reason="library avatars are fetched, not committed (tools/fetch_library.py)")
def test_on_a_real_character_no_seam_parts_and_the_file_is_what_the_pass_left(tool):
    """AvatarSample C in denim shorts under her own top: the look the 1.8 mm was reported on."""
    rows = asyncio.run(tool.trace([("avatar-sample-c", "shorts-denim-v1")], "blue"))
    assert len(rows) == 1 and "completed" in rows[0]["state"]
    bottom = next(g for g in rows[0]["garments"] if g["isTheBottom"])
    assert bottom["keptTopTuck"]["version"] == 3 and bottom["movedVertices"] > 0
    assert bottom["seamPairs"] > 0 and bottom["seamGapAfterPassMm"] == 0.0 and bottom["seamGapExportedMm"] == 0.0
    assert bottom["exportedIsWhatThePassLeft"] is True
    assert bottom["heightChangedMm"] == 0.0 and bottom["flippedTriangles"] == 0
    assert bottom["degenerateTriangles"] == bottom["degenerateBefore"]
    for garment in rows[0]["garments"]:  # her foundation goes under the top too
        assert garment["seamGapAfterPassMm"] == 0.0


def test_where_the_pass_does_not_run_nothing_moves(tool):
    """AvatarSample O (committed): no kept top over these jeans, so the mesh is the shell."""
    rows = asyncio.run(tool.trace([(KEEPS_A_TOP, "jeans-straight-v1")], "blue"))
    bottom = next(g for g in rows[0]["garments"] if g["isTheBottom"])
    assert bottom["keptTopTuck"] is None and bottom["movedVertices"] == 0
    assert bottom["edgeRatio"] == [1.0, 1.0] and bottom["exportedIsWhatThePassLeft"] is True
