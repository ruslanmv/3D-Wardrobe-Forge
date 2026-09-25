"""The shared fit model: what a fitted stocking and a fitted belt publish.

This fixes finding G1 of HOSIERY_STYLING. The old garter took a stocking-top
height from a formula (``hip_y - thigh * 0.4``) that the stockings computed
separately, so two garments agreed only for as long as nobody changed either
formula, and never agreed with what fitting did to the band afterwards.

Now there is one answer, taken from geometry. When the legwear layer has been
built, fitted and skin-bound, its band's rings are read back off the mesh and
published as a ``FittedStockingTop`` per leg: the band's top and bottom rings
where fitting left them, its outward normals, and one ``ClipPoint`` per strap
position, carrying both the world position and the surface coordinates (how far
round the leg, how far down the band) plus the skin binding of the band there.
The straps end at those points, the hardware sits at them, and the reveal solver
measures the hem against the same rings. None of them recomputes a height.

Positions are rest-pose world space, like every garment in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Where the clips sit round the leg, as a fraction of a turn from her front centre,
#: positive toward her outside. Front clips a touch outward of the centre line, as
#: sewn belts hang them; the back clip a third of a turn round (30° behind her side),
#: not at the back centre. Measured on the calibration mannequin, a back clip at 0.4
#: turns pulled 4.5% walking, at 0.33 turns 2.7%, and at the back centre far more
#: (``suspender_straps`` explains why). The fit report shows the numbers every time.
CLIP_TURNS: dict[str, float] = {"front": 0.03, "outer": 0.25, "back": 0.33}

#: Which clips a belt with this many straps uses on each leg.
CLIPS_FOR: dict[int, tuple[str, ...]] = {4: ("front", "back"), 6: ("front", "outer", "back")}

#: Where the clasp grips the band, below its top edge: the button presses the welt
#: a third of the way down, never more than 1.5 cm.
GRIP_FRACTION = 0.35
GRIP_MAX_M = 0.015


@dataclass(frozen=True)
class ClipPoint:
    """One strap's attachment on a stocking band."""

    name: str
    side: str
    #: World position on the band's surface (rest pose).
    position: np.ndarray
    #: Outward surface normal there, and the unit direction down the leg along the band.
    normal: np.ndarray
    tangent: np.ndarray
    #: Surface coordinates: turns round the leg from her front (outward positive), and
    #: metres below the band's top edge.
    u: float
    v: float
    #: The band vertex it was taken from, and that vertex's skin binding (bone names).
    vertex: int
    bones: tuple[str, ...] = ()
    weights: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name, "side": self.side,
            "position": [round(float(c), 5) for c in self.position],
            "normal": [round(float(c), 4) for c in self.normal],
            "u": round(self.u, 4), "v": round(self.v, 4),
            "bones": list(self.bones), "weights": [round(w, 4) for w in self.weights],
        }


@dataclass(frozen=True)
class FittedStockingTop:
    """A stocking's top band after fitting: the one authority on where it is."""

    side: str
    #: Heights of the band's top and bottom edges: the mean of each fitted ring.
    top_y: float
    bottom_y: float
    #: The fitted rings, (N, 3), round the leg from her back, and outward normals per vertex.
    top_ring: np.ndarray
    bottom_ring: np.ndarray
    normals: np.ndarray
    #: Mean band width measured on the surface, metres.
    width_m: float
    #: The leg axis (hip joint -> knee) the band sits on.
    axis_origin: np.ndarray
    axis: np.ndarray
    clips: dict[str, ClipPoint] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "topY": round(self.top_y, 4),
            "bottomY": round(self.bottom_y, 4),
            "widthMm": round(self.width_m * 1000.0, 1),
            "clips": {name: clip.to_dict() for name, clip in self.clips.items()},
        }


@dataclass(frozen=True)
class FittedBelt:
    """A suspender belt (or waspie, or guêpière) after fitting: its lower edge takes the straps."""

    style: str
    #: The fitted bottom ring, (N, 3), and the top ring.
    bottom_ring: np.ndarray
    top_ring: np.ndarray
    bottom_y: float
    top_y: float
    #: How far the fitted belt stands off her, for the strap's tab to lie on it.
    clearance_m: float
    #: The belt's skin binding at each bottom-ring vertex, as bone names and weights.
    bones: list[tuple[str, ...]] = field(default_factory=list)
    weights: list[tuple[float, ...]] = field(default_factory=list)

    def tab(self, x: float, forward_sign: float) -> tuple[np.ndarray, int]:
        """The point on the bottom edge at ``x``, on her front (+1) or back (-1), and its index."""
        ring = self.bottom_ring
        facing = ring[:, 2] * forward_sign
        # The half of the ring on the asked-for face; of those, the vertex nearest x,
        # then linear interpolation to exactly x with its neighbour.
        candidates = np.where(facing > 0)[0]
        if candidates.size == 0:
            candidates = np.arange(ring.shape[0])
        nearest = candidates[np.argmin(np.abs(ring[candidates, 0] - x))]
        return ring[nearest].astype(np.float64), int(nearest)

    def to_dict(self) -> dict:
        return {"style": self.style, "topY": round(self.top_y, 4), "bottomY": round(self.bottom_y, 4)}


def ring_normals(ring: np.ndarray, centre: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """Outward normals of a ring round a leg: away from its axis, perpendicular to it."""
    radial = ring - centre
    radial -= np.outer(radial @ axis, axis)
    lengths = np.linalg.norm(radial, axis=1, keepdims=True)
    return radial / np.maximum(lengths, 1e-9)


__all__ = [
    "CLIPS_FOR",
    "CLIP_TURNS",
    "ClipPoint",
    "FittedBelt",
    "FittedStockingTop",
    "GRIP_FRACTION",
    "GRIP_MAX_M",
    "ring_normals",
]
