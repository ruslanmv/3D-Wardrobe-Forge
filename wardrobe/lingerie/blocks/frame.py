"""Where on her a block's pattern coordinates land: angle round her and height, to a point.

A block is drawn in body coordinates, ``phi`` round her from her centre front
(positive toward +x) and height ``y``, as a pattern-maker drafts on a dress
form's grid. Here those become points: on the measured outline at that height
(``torsoProfile``, every 1.5 cm) plus the fabric's clearance, with heights taken
from her landmarks (``lingerieLandmarks``). Nothing here is a bone ratio unless
the body gave nothing to measure, and then it says so through the landmarks'
own sources and warnings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.procedural import FitParameters, crotch_y, half_at
from wardrobe.lingerie.landmarks import BodyLandmarks
from wardrobe.lingerie.surface import DepthMap


@dataclass
class BodyFrame:
    params: FitParameters
    marks: BodyLandmarks
    table: np.ndarray | None  # [y, half-width, half-depth, cx, cz], ascending y

    def surface(self, x: float, y: float, side: str, lift: float) -> np.ndarray | None:
        """A point ``lift`` off her measured front or back at (x, y), interpolated (``DepthMap``)."""
        depth_map = DepthMap.of(self.params)
        return depth_map.point(x, y, side, lift) if depth_map is not None else None

    @property
    def forward(self) -> float:
        return self.params.forward

    @property
    def clearance(self) -> float:
        return self.params.clearance_m

    def outline(self, y: float) -> tuple[float, float, float, float]:
        """(half-width, half-depth, cx, cz) of her at ``y``: measured, or the landmark rings' if not."""
        if self.table is not None and self.table.shape[0] >= 4:
            t = self.table
            return tuple(float(np.interp(y, t[:, 0], t[:, k])) for k in (1, 2, 3, 4))  # type: ignore[return-value]
        half_w, half_d = half_at(self.params, y)
        return half_w, half_d, 0.0, 0.0

    def point(self, phi, y, offset: float | None = None) -> np.ndarray:
        """Points at angles ``phi`` round her at heights ``y`` (array or scalar), ``offset`` off her."""
        offset = self.clearance if offset is None else offset
        phi = np.atleast_1d(np.asarray(phi, dtype=np.float64))
        ys = np.broadcast_to(np.asarray(y, dtype=np.float64), phi.shape)
        out = np.empty((phi.size, 3))
        for k, (angle, height) in enumerate(zip(phi, ys, strict=True)):
            a, b, cx, cz = self.outline(float(height))
            out[k] = (cx + (a + offset) * np.sin(angle), height,
                      cz + self.forward * (b + offset) * np.cos(angle))
        return out


def body_frame(params: FitParameters) -> BodyFrame:
    """The frame for ``params``: her landmarks and outline if measured, formulas otherwise."""
    meta = params.metadata
    table = None
    if meta.get("torsoProfile"):
        table = np.asarray(meta["torsoProfile"], dtype=np.float64)
        table = table[np.argsort(table[:, 0])]
    marks = meta.get("lingerieLandmarks")
    if isinstance(marks, dict):
        landmarks = BodyLandmarks.from_dict(marks)
    else:
        crotch = crotch_y(params, params.hip_y - (params.hip_y - params.knee_y) * 0.12)
        underbust = params.chest_y - (params.chest_y - params.waist_y) * 0.32
        half = half_at(params, params.chest_y)[0]
        landmarks = BodyLandmarks(
            forward=params.forward, centre_x=0.0, crotch_y=crotch, full_hip_y=params.hip_y,
            high_hip_y=(params.hip_y + params.waist_y) / 2, waist_y=params.waist_y,
            underbust_y={"left": underbust, "right": underbust},
            bust_points={side: [sign * half * 0.45, params.chest_y, 0.0]
                         for side, sign in (("left", 1.0), ("right", -1.0))},
            sternum=[0.0, (params.chest_y + underbust) / 2, 0.0],
            sources=dict.fromkeys(("crotch", "waist", "fullHip", "bustPoints", "underbust"), "formula"),
            warnings=["no landmarks measured: every landmark is by formula"],
        )
    return BodyFrame(params=params, marks=landmarks, table=table)


__all__ = ["BodyFrame", "body_frame"]
