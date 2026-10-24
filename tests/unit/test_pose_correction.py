"""PS4. The wide-sit lap: an edge pulled several times its length comes back,
and a vertex inside the skin is pushed out. The body array is not rewritten.
"""

import numpy as np

from wardrobe.vrm.pose_correction import STRETCH_LIMIT, correct


def test_a_vertex_inside_the_skin_is_pushed_out_and_the_body_stays():
    rest = np.array([[0.0, 0.0, 0.0], [0.04, 0.0, 0.0], [0.02, 0.0, 0.01]])
    posed = np.array([[0.0, -0.02, 0.0], [0.04, -0.02, 0.0], [0.02, -0.02, 0.01]])
    body = rest.copy()
    normals = np.tile([0.0, 1.0, 0.0], (3, 1))
    out = correct(posed, rest, np.array([0, 1, 2]), np.ones(3, dtype=bool), body, normals)
    assert out[:, 1].min() >= 0.0015 - 1e-4
    assert np.array_equal(body, rest)


def test_inner_thigh_normals_do_not_pin_the_hem_open():
    rest = np.array([[-0.02, 0.0, 0.0], [0.02, 0.0, 0.0], [0.0, 0.01, 0.0]])
    posed = np.array([[-0.10, 0.0, 0.0], [0.10, 0.0, 0.0], [0.0, 0.01, 0.0]])
    normals = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    out = correct(posed, rest, np.array([0, 1, 2]), np.ones(3, dtype=bool), posed, normals)
    stretched = np.linalg.norm(out[0] - out[1]) / 0.04
    assert stretched <= STRETCH_LIMIT + 0.2


def test_a_hem_vertex_is_pulled_back_to_a_pinned_skirt_vertex():
    rest = np.array([[0.0, 0.0, 0.0], [0.0, 0.04, 0.0], [0.01, 0.02, 0.0]])
    posed = np.array([[0.0, -0.12, 0.0], [0.0, 0.04, 0.0], [0.01, -0.04, 0.0]])
    lap = np.array([True, False, True])
    out = correct(posed, rest, np.array([0, 1, 2]), lap, np.zeros((0, 3)), np.zeros((0, 3)))
    assert np.allclose(out[1], posed[1])
    span = float(np.linalg.norm(out[0] - out[1]) / 0.04)
    assert span <= STRETCH_LIMIT + 0.2


def test_an_edge_opened_across_the_lap_comes_back_under_the_stretch_limit():
    rest = np.array([[0.0, 0.0, 0.0], [0.04, 0.0, 0.0], [0.02, 0.01, 0.0]])
    posed = np.array([[-0.08, 0.0, 0.0], [0.12, 0.0, 0.0], [0.02, 0.01, 0.0]])
    out = correct(posed, rest, np.array([0, 1, 2]), np.ones(3, dtype=bool), np.zeros((0, 3)), np.zeros((0, 3)))
    stretched = np.linalg.norm(out[0] - out[1]) / 0.04
    assert stretched <= STRETCH_LIMIT + 0.2
