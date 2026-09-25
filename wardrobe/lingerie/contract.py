"""What one lingerie piece publishes for the others to use: anchors, straps, elastic edges.

The hosiery rebuild fixed suspenders by making one component the authority on
where it is (``FittedStockingTop``) and every other component read that, never
a formula of its own (``wardrobe/hosiery/contract.py``). The same rule is the
point of this module. A bra strap does not guess where the cup peak is; the cup
publishes it as an :class:`Anchor`, and the strap ends there. A strap reports a
rest length and its length in each pose, so "is it too tight" has a number.

``Anchor`` is ``hosiery.contract.ClipPoint`` generalised (a clip is one kind of
anchor); ``ClipPoint`` itself stays as it is, so the suspenders do not move.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Anchor:
    """A point one piece publishes for another to attach to."""

    name: str
    side: str  # "left" | "right" | "centre"
    position: np.ndarray
    #: Outward surface normal there, and the direction a strap leaves it.
    normal: np.ndarray
    tangent: np.ndarray
    #: Which piece published it ("cup", "band", "brief", ...) or "formula" when none did.
    source: str = "formula"
    vertex: int = -1
    bones: tuple[str, ...] = ()
    weights: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name, "side": self.side, "source": self.source,
            "position": [round(float(c), 5) for c in self.position],
            "normal": [round(float(c), 4) for c in self.normal],
            "tangent": [round(float(c), 4) for c in self.tangent],
        }


@dataclass(frozen=True)
class ElasticSpec:
    """An elastic as a component: its width and how hard it pulls at each stretch.

    ``force_curve`` is (strain, newtons per full width) pairs from a
    force-extension test (ASTM D4964 is the usual method for elastic fabrics),
    rising, first point (0, 0). ``cut_ratio`` is how short the elastic is cut
    against the edge it is sewn to: 0.9 means 10% shorter, so it is stretched
    10% on the flat garment and more on the body. Values here are typical of
    their class, not a supplier's measured lot: a production style replaces them
    with the lot's own curve.
    """

    name: str
    width_mm: float
    force_curve: tuple[tuple[float, float], ...]
    cut_ratio: float = 1.0
    thickness_mm: float = 1.0

    def force(self, strain: float) -> float:
        """Newtons at ``strain`` (negative strain: slack, no force); linear past the last point."""
        if strain <= 0.0:
            return 0.0
        xs = [s for s, _ in self.force_curve]
        ys = [f for _, f in self.force_curve]
        if strain <= xs[-1]:
            return float(np.interp(strain, xs, ys))
        slope = (ys[-1] - ys[-2]) / max(xs[-1] - xs[-2], 1e-9)
        return float(ys[-1] + slope * (strain - xs[-1]))

    def to_dict(self) -> dict:
        return {"name": self.name, "widthMm": self.width_mm, "cutRatio": self.cut_ratio,
                "thicknessMm": self.thickness_mm, "forceCurve": [list(p) for p in self.force_curve]}


@dataclass(frozen=True)
class StrapSpec:
    """A strap as it is made: a flat ribbon, usually of strap elastic, often with a slider."""

    width_m: float = 0.010
    thickness_m: float = 0.0012
    elastic: ElasticSpec | None = None
    adjustable: bool = True
    #: Where along the back half of the strap the slider sits (0 at the back anchor).
    slider_fraction: float = 0.3
    #: Worn standing, a strap is stretched this much over its rest length: it holds.
    worn_stretch: float = 0.04


#: Stretch thresholds for a strap, as for the suspenders (HOSIERY_STYLING §4.2).
STRAP_STRETCH_WARN = 0.08
STRAP_STRETCH_ERROR = 0.15
STRAP_SLACK_BELOW = -0.03


@dataclass
class FittedStrap:
    """A strap after fitting: its two anchors, its path, and how long it is at rest and in each pose."""

    name: str
    side: str
    front: Anchor
    back: Anchor
    path: np.ndarray
    spec: StrapSpec
    rest_length: float
    current: dict[str, float] = field(default_factory=dict)
    stretch: dict[str, float] = field(default_factory=dict)

    def status(self, pose: str) -> str:
        s = self.stretch.get(pose, 0.0)
        if s > STRAP_STRETCH_ERROR:
            return "error"
        if s > STRAP_STRETCH_WARN:
            return "warning"
        return "slack" if s < STRAP_SLACK_BELOW else "ok"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "side": self.side, "front": self.front.to_dict(), "back": self.back.to_dict(),
            "widthMm": round(self.spec.width_m * 1000, 2),
            "thicknessMm": round(self.spec.thickness_m * 1000, 2),
            "restLengthM": round(self.rest_length, 4),
            "currentM": {k: round(v, 4) for k, v in self.current.items()},
            "stretch": {k: round(v, 4) for k, v in self.stretch.items()},
            "status": {k: self.status(k) for k in self.stretch},
        }


__all__ = ["Anchor", "ElasticSpec", "FittedStrap", "STRAP_SLACK_BELOW", "STRAP_STRETCH_ERROR",
           "STRAP_STRETCH_WARN", "StrapSpec"]
