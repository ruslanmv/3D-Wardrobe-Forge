"""BS2. The collision body, the state that carries it, and signed clearance against her.

**Two surfaces, not one.** The *render* body is what she looks like (her skin plus any made
regions). The *collision* body is what cloth is fitted against: the same topology, made

* **less detailed** — a region keeps only its ``collisionDetail`` share of its displacement
  (a navel's hollow is mostly left out: cloth bridges a navel, it does not dip into it);
* **smoother** — Taubin-smoothed at the profile's ``detailCutoffMm`` (in edges: on a VRoid
  torso, whose edges are 13 mm, a 3 mm cutoff smooths nothing, because there is nothing that
  fine to suppress — the mesh cannot hold it);
* **never inside her** — a vertex moves only outward along its normal (``max(0, ·)``), so
  smoothing fills hollows and never shaves a curve;
* **slightly proud** — plus ``outwardMarginMm`` everywhere, the cloth's numerical shell.

So the collision body contains the render body. That is the property everything relies on:
a garment that clears the collision body clears her.

**Never destructive.** ``base`` is her buffer as it came in and is never modified; ``render``
and ``collision`` are derived from it. The VRM's own POSITION data is not touched by any of
this — a made region reaches the export only as a morph target (``export``), on request.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.body_surface import geometry as g
from wardrobe.body_surface.regions import MorphTarget, RegionResult
from wardrobe.body_surface.surface import SkinPart

#: Garment samples are taken this far apart for the clearance metric.
CLEARANCE_SPACING_M = 0.008
#: Distances farther than this from her are not clearance questions.
CLEARANCE_REACH_M = 0.03
#: A penetration whose nearest inside and outside surfaces differ by less than this is uncertain.
AMBIGUITY_M = 0.0015
#: Contact queries (the XPBD pass) need only the last centimetre: a finer grid, ten times faster.
CONTACT_REACH_M = 0.01
#: Taubin passes are capped: past this the collision body would lose her shape, not detail.
MAX_SMOOTHING_PASSES = 30


@dataclass
class BodySurfaceState:
    profile_id: str
    capability: str
    detail_level: str
    parts: list[SkinPart]
    base: dict[int, np.ndarray]
    render: dict[int, np.ndarray]
    collision: dict[int, np.ndarray]
    morphs: list[MorphTarget] = field(default_factory=list)
    regions: list[RegionResult] = field(default_factory=list)
    #: Close-fit cloth clearance from the profile, metres, or None.
    close_fit_clearance_m: float | None = None
    provenance: dict = field(default_factory=dict)
    envelope: dict = field(default_factory=dict)
    _render_grid: g.TriangleGrid | None = None
    _collision_grid: g.TriangleGrid | None = None

    # ---- what the fitter reads -----------------------------------------------------------
    def collision_positions(self) -> dict[int, np.ndarray]:
        """POSITION accessor -> collision positions, for ``body_points(positions=…)``."""
        return {k: v.astype(np.float64) for k, v in self.collision.items()}

    def render_grid(self) -> g.TriangleGrid:
        if self._render_grid is None:
            self._render_grid = _grid(self.parts, self.render, reach=CLEARANCE_REACH_M)
        return self._render_grid

    def collision_grid(self) -> g.TriangleGrid:
        if self._collision_grid is None:
            self._collision_grid = _grid(self.parts, self.collision, reach=CONTACT_REACH_M)
        return self._collision_grid

    def to_report(self) -> dict:
        return {
            "profile": self.profile_id,
            "capability": self.capability,
            "detailLevel": self.detail_level,
            "regions": [r.to_dict() for r in self.regions],
            "morphTargets": sorted({m.name for m in self.morphs}),
            "morphTargetsValid": not any(m.problems() for m in self.morphs),
            "collision": self.envelope,
        }


def _grid(parts: list[SkinPart], positions: dict[int, np.ndarray], *, reach: float = 0.03) -> g.TriangleGrid:
    stacked, triangles, offset = [], [], 0
    for part in parts:
        stacked.append(positions[part.accessor])
        triangles.append(part.triangles + offset)
        offset += positions[part.accessor].shape[0]
    return g.TriangleGrid(np.vstack(stacked), np.vstack(triangles), reach=reach)


def build_envelope(part: SkinPart, source: np.ndarray, *, margin_m: float,
                   cutoff_m: float) -> tuple[np.ndarray, dict]:
    """The collision positions for one buffer: smoothed, outward-only, plus the margin."""
    used = part.used
    # On the welded mesh: seam copies offset along one-sided normals would part, and open a crack
    # in the collision body exactly where a garment's seam sits (geometry.weld).
    owner, welded, tri = g.weld(source, part.triangles)
    edges = g.unique_edges(tri)
    lengths = np.linalg.norm(welded[edges[:, 0]] - welded[edges[:, 1]], axis=1)
    edge = float(np.median(lengths)) if lengths.size else 0.0
    # Detail of wavelength ~cutoff is a few edges long when the mesh holds it at all: Taubin's
    # pass band falls off over about (cutoff / edge)² passes.
    passes = int(np.clip(round((cutoff_m / edge) ** 2 * 2), 0, MAX_SMOOTHING_PASSES)) if edge > 0 else 0
    normals_w = g.vertex_normals(welded, tri)
    smoothed = g.taubin_smooth(welded, tri, passes) if passes else welded
    fill_w = np.maximum(0.0, np.einsum("ij,ij->i", smoothed - welded, normals_w))
    normals, fill = normals_w[owner], fill_w[owner]
    out = source.astype(np.float64).copy()
    out[used] = source[used] + normals[used] * (fill[used] + margin_m)[:, None]
    return out, {"smoothingPasses": passes, "medianEdgeMm": round(edge * 1000, 2),
                 "filledMaxMm": round(float(fill[used].max()) * 1000, 3) if used.size else 0.0}


def build_state(parts: list[SkinPart], render: dict[int, np.ndarray], morphs: list[MorphTarget],
                regions: list[RegionResult], profile, detail_level: str) -> BodySurfaceState:
    base = {p.accessor: p.positions for p in parts}
    detail = {r.key: r.collision_detail for r in profile.regions}
    region_of = {("Body" + r.key[:1].upper() + r.key[1:]): r.key for r in profile.regions}
    collision, envelope = {}, {}
    for part in parts:
        # The collision body starts from her base skin plus each region's collisionDetail share.
        source = base[part.accessor].astype(np.float64).copy()
        for morph in morphs:
            if morph.accessor == part.accessor:
                share = detail.get(region_of.get(morph.name, ""), 0.0)
                source[morph.indices] += morph.deltas.astype(np.float64) * share
        collision[part.accessor], envelope[str(part.accessor)] = build_envelope(
            part, source, margin_m=profile.outward_margin_m, cutoff_m=profile.detail_cutoff_m)
    return BodySurfaceState(
        profile_id=profile.id, capability=str(profile.capability), detail_level=detail_level, parts=parts,
        base=base, render=render, collision=collision, morphs=morphs, regions=regions,
        close_fit_clearance_m=profile.close_fit_clearance_m, provenance=dict(profile.provenance),
        envelope={"outwardMarginMm": round(profile.outward_margin_m * 1000, 3),
                  "detailCutoffMm": round(profile.detail_cutoff_m * 1000, 3), "buffers": envelope},
    )


def signed_clearance(grid: g.TriangleGrid, positions: np.ndarray, triangles: np.ndarray) -> dict:
    """How far a garment's surface stands from her: vertices, edge midpoints and face samples.

    One number is not enough — a single 0.6 mm numerical speck and a palm-sized patch through
    her have the same minimum — so the share of samples below −0.5 mm and −1 mm is reported
    beside it. Samples farther than the reach are not near her and are not counted.
    """
    tri = triangles.reshape(-1, 3)
    samples, _, _ = g.surface_samples(positions, tri, CLEARANCE_SPACING_M)
    edges = g.unique_edges(tri)
    mids = (positions[edges[:, 0]] + positions[edges[:, 1]]) / 2
    points = np.vstack([positions.astype(np.float64), mids, samples])
    d = grid.signed_distance(points)
    near = np.isfinite(d)
    if not near.any():
        return {"samples": 0}
    penetrating = near & (d < -0.0005)
    uncertain = int(grid.ambiguous(points[penetrating], AMBIGUITY_M).sum()) if penetrating.any() else 0
    d = d[near]
    return {
        # Penetrating samples whose sign is uncertain (a narrow hollow: both walls within 1.5 mm).
        "uncertainPenetratingSamples": uncertain,
        "samples": int(d.size),
        "minimumSignedDistanceMm": round(float(d.min()) * 1000, 3),
        "meanPenetrationMm": round(float(np.minimum(d, 0).mean()) * 1000, 4),
        "samplesBelowMinus0_5Mm": int((d < -0.0005).sum()),
        "samplesBelowMinus1Mm": int((d < -0.001).sum()),
        "shareBelowMinus0_5Mm": round(float((d < -0.0005).mean()), 5),
    }


__all__ = ["BodySurfaceState", "build_envelope", "build_state", "signed_clearance"]
