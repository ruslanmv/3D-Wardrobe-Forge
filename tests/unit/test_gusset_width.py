"""A brief's gusset that pinched to a string is opened back to the mound panel.

The seams stay where they meet the front and back panels. A string, whose seams
are narrow because it was drafted that way, is not opened into a brief.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.lingerie.fit import restore_gusset_width


def _grid(seam_mm: float, middle_mm: float) -> tuple[np.ndarray, list[list[int]]]:
    """Three rows of five vertices. y and z are a strip; only x carries the width."""
    def row(z: float, width_mm: float) -> np.ndarray:
        xs = np.linspace(-width_mm / 2, width_mm / 2, 5) / 1000.0
        return np.stack([xs, np.full(5, 0.80), np.full(5, z)], axis=1)

    positions = np.vstack([row(-0.08, seam_mm), row(0.0, middle_mm), row(0.08, seam_mm)])
    grid = [list(range(0, 5)), list(range(5, 10)), list(range(10, 15))]
    return positions, grid


def _span(positions: np.ndarray, row: list[int]) -> float:
    return float(np.ptp(positions[row, 0]))


def test_a_pinched_brief_gusset_opens_to_24mm_and_the_seams_stay():
    positions, grid = _grid(seam_mm=70.0, middle_mm=5.0)
    seams = (_span(positions, grid[0]), _span(positions, grid[-1]))

    assert restore_gusset_width(positions, grid) is True

    assert _span(positions, grid[1]) == pytest.approx(0.024)
    assert _span(positions, grid[0]) == seams[0]
    assert _span(positions, grid[-1]) == seams[1]
    # The middle of the row did not walk sideways, and y/z were not touched.
    assert abs(float(positions[grid[1], 0].mean())) < 1e-9
    assert np.allclose(positions[grid[1], 1], 0.80)
    assert np.allclose(positions[grid[1], 2], 0.0)


def test_a_string_is_left_narrow():
    positions, grid = _grid(seam_mm=12.0, middle_mm=5.0)
    before = positions.copy()

    assert restore_gusset_width(positions, grid) is False
    assert np.array_equal(positions, before)


def test_a_row_already_on_the_mound_is_left_alone():
    positions, grid = _grid(seam_mm=70.0, middle_mm=30.0)
    before = positions.copy()

    assert restore_gusset_width(positions, grid) is False
    assert np.array_equal(positions, before)


def test_the_opened_row_is_never_wider_than_its_seams():
    positions, grid = _grid(seam_mm=41.0, middle_mm=8.0)

    # A floor wider than the seams must still stop at the narrower seam.
    assert restore_gusset_width(positions, grid, floor_m=0.080) is True
    assert _span(positions, grid[1]) == pytest.approx(0.041)
