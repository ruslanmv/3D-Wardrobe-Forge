"""BS3. A profile's regions, made into same-topology morph targets on her skin.

For each region, on each POSITION buffer of her skin (``surface.skin_parts``):

1. **Anchor** — the template's anchor located on her landmarks (``anchors.locate``).
2. **Support** — her vertices within the template's radius *along her surface* (geodesic, so
   a belly region cannot reach an arm resting beside it), scaled by her waist width against
   the template's reference.
3. **Registration** — her surface near the anchor is charted in a tangent frame (u across
   her, v up her). The template's chart landmarks are matched to hers — to a measured body
   landmark when the template binds one, else to its own position scaled to her — and a 2-D
   RBF warp (Wendland kernel, affine part) maps her chart into the template's.
4. **Field** — the template's (dn, du, dv) is sampled at each warped point and expressed in
   her own local frame (her vertex normal, the chart's u and v), times a C² Wendland mask
   of geodesic distance so it fades to nothing at the edge of the support.
5. **Blend** — argmin ‖Δ − Δ₀‖² + λ‖LΔ‖² with everything outside the support held still:
   the result meets the untouched body with no step (no "sticker" edge).
6. **Checks** — a region whose support holds fewer than ``MIN_REGION_VERTICES`` of her
   vertices is not made: her mesh cannot express it, and a three-vertex dent is worse than
   none (normal maps are the tool for detail finer than her mesh). A region that changes a
   measurement it promised to preserve by more than ``MAX_MEASUREMENT_CHANGE`` is dropped,
   so an anatomical detail can never quietly change the size her garments are made at.

Nothing here writes to the document. The deltas are kept sparse (indices + offsets), as glTF
allows a target to name only what moves; ``export`` densifies them when it writes the VRM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from wardrobe.body_surface import geometry as g
from wardrobe.body_surface.anchors import landmark_points, locate
from wardrobe.body_surface.library import Profile, Region, Template
from wardrobe.body_surface.surface import SkinPart

#: Fewer of her vertices than this inside a region's support, and the region is not made.
MIN_REGION_VERTICES = 8
#: A morph may change an unaffected measurement by at most this fraction (0.5%).
MAX_MEASUREMENT_CHANGE = 0.005
#: Her waist width is clamped to this range of the template's reference before scaling it.
SCALE_RANGE = (0.7, 1.4)
#: An anchor farther than this from her nearest skin vertex is not on this buffer.
ANCHOR_REACH_M = 0.05
#: A delta shorter than this is not a change (glTF sparse targets name only what moves).
EPSILON_M = 1e-6
#: Girths are taken in a slab this thick, metres.
GIRTH_SLAB_M = 0.006


@dataclass
class MorphTarget:
    """A sparse same-topology delta for one POSITION buffer."""

    name: str
    accessor: int
    count: int  # the buffer's vertex count: a target must match it
    indices: np.ndarray  # (K,) uint32
    deltas: np.ndarray  # (K, 3) float32
    default_weight: float = 1.0

    def dense(self) -> np.ndarray:
        out = np.zeros((self.count, 3), dtype=np.float32)
        out[self.indices] = self.deltas
        return out

    def problems(self) -> list[str]:
        """What would make this an invalid glTF morph target."""
        issues = []
        if not np.isfinite(self.deltas).all():
            issues.append(f"{self.name}: NaN or infinite delta")
        if self.indices.size and (self.indices.max() >= self.count):
            issues.append(f"{self.name}: index past the end of its buffer")
        if self.indices.shape[0] != self.deltas.shape[0]:
            issues.append(f"{self.name}: indices and deltas differ in count")
        return issues


@dataclass
class RegionResult:
    key: str
    template_id: str
    made: bool
    reason: str = ""
    vertices: int = 0
    max_offset_mm: float = 0.0
    registration_mm: float = 0.0
    measurements: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"region": self.key, "template": self.template_id, "made": self.made}
        if self.reason:
            out["reason"] = self.reason
        if self.made:
            out.update(vertices=self.vertices, maxOffsetMm=round(self.max_offset_mm, 2),
                       registrationMm=round(self.registration_mm, 3), measurements=self.measurements)
        return out


def _scale(template: Template, waist_width_m: float) -> float:
    return float(np.clip(waist_width_m / max(template.reference_waist_m, 1e-6), *SCALE_RANGE))


def region_delta(part: SkinPart, normals: np.ndarray, ring: list[np.ndarray], template: Template,
                 region: Region, anchor_position: np.ndarray, forward: np.ndarray,
                 body_marks: dict[str, np.ndarray], scale: float) -> tuple[np.ndarray, int, float, str]:
    """One region on one buffer: (Δ (N, 3), vertices in support, registration error m, why not)."""
    pos = part.positions
    used = part.used
    facing = used[normals[used] @ forward > 0.2]
    if not facing.size:
        return np.zeros_like(pos), 0, 0.0, "no skin faces the region's way on this buffer"
    gap = np.linalg.norm(pos[facing] - anchor_position, axis=1)
    if gap.min() > ANCHOR_REACH_M:
        return np.zeros_like(pos), 0, 0.0, "the anchor is not on this buffer"
    nearest = facing[np.argsort(gap)[:3]]
    radius = template.radius_m * scale
    seeds = {int(v): float(np.linalg.norm(pos[v] - anchor_position)) for v in nearest}
    geo = g.geodesic_distance(pos, ring, seeds, limit=radius)
    inside = np.flatnonzero(np.isfinite(geo) & (geo < radius))
    if inside.size < MIN_REGION_VERTICES:
        return (np.zeros_like(pos), int(inside.size), 0.0,
                f"her mesh has {inside.size} vertices inside this {radius * 100:.1f} cm region; a morph "
                f"needs {MIN_REGION_VERTICES} (finer detail belongs in a normal map)")

    # Chart her surface in the tangent frame at the anchor.
    centre_normal = normals[nearest].mean(axis=0)
    u_axis, v_axis = g.tangent_basis(centre_normal)
    rel = pos[inside] - anchor_position
    chart = np.column_stack([rel @ u_axis, rel @ v_axis])

    # Register: template landmarks (template chart) <- her landmarks (her chart).
    template_uv, body_uv = [], []
    for spec in template.landmarks.values():
        uv = np.asarray(spec.get("uv", (0.0, 0.0)), dtype=np.float64)
        bound = spec.get("bodyLandmark")
        if bound and bound in body_marks:
            offset = body_marks[bound] - anchor_position
            body_uv.append((offset @ u_axis, offset @ v_axis))
        else:
            body_uv.append(tuple(uv * scale))
        template_uv.append(tuple(uv))
    if not template_uv:
        template_uv, body_uv = [(0.0, 0.0)], [(0.0, 0.0)]
    warp = g.RbfWarp2D(np.asarray(body_uv), np.asarray(template_uv))
    residual = float(np.linalg.norm(warp(np.asarray(body_uv)) - np.asarray(template_uv), axis=1).max())

    sampled = template.sample(warp(chart))  # (dn, du, dv), template metres
    mask = g.wendland(geo[inside] / radius)[:, None]
    local = (sampled[:, :1] * normals[inside] + sampled[:, 1:2] * u_axis + sampled[:, 2:3] * v_axis)
    desired = np.zeros_like(pos)
    desired[inside] = mask * local * scale * region.strength
    blended = g.laplacian_blend(desired, ring, inside, smoothness=region.smoothness)
    return blended, int(inside.size), residual, ""


def girths(points: np.ndarray, marks, *, centre_x: float) -> dict[str, float]:
    """Tape-measure girths of her at the landmark heights (convex hull of a thin slice)."""
    levels = {"underbust": marks.underbust(), "waist": marks.waist_y, "high-hip": marks.high_hip_y,
              "full-hip": marks.full_hip_y}
    out = {}
    for name, y in levels.items():
        slab = points[np.abs(points[:, 1] - y) < GIRTH_SLAB_M]
        if slab.shape[0] >= 8:
            out[name] = g.convex_perimeter(slab[:, [0, 2]])
    thigh_y = marks.crotch_y - 0.05
    slab = points[(np.abs(points[:, 1] - thigh_y) < GIRTH_SLAB_M) & (points[:, 0] > centre_x)]
    if slab.shape[0] >= 8:
        out["thigh"] = g.convex_perimeter(slab[:, [0, 2]])
    return out


def _surface_cloud(parts: list[SkinPart], positions: dict[int, np.ndarray]) -> np.ndarray:
    clouds = []
    for part in parts:
        pos = positions[part.accessor]
        samples, _, _ = g.surface_samples(pos, part.triangles, 0.006)
        clouds += [pos[part.used], samples]
    return np.vstack(clouds) if clouds else np.zeros((0, 3))


def build_regions(parts: list[SkinPart], profile: Profile, marks, waist_width_m: float
                  ) -> tuple[dict[int, np.ndarray], list[MorphTarget], list[RegionResult]]:
    """Every region of the profile on her: (render positions per buffer, morph targets, per-region record)."""
    base = {p.accessor: p.positions for p in parts}
    render = {k: v.copy() for k, v in base.items()}
    # Regions are computed on each buffer welded (geometry.weld) and given back to every seam
    # copy: computed per copy, a region crossing a UV seam would open it.
    welded: dict[int, tuple[np.ndarray, SkinPart]] = {}
    for p in parts:
        owner, positions, triangles = g.weld(p.positions, p.triangles)
        welded[p.accessor] = (owner, SkinPart(p.accessor, p.primitives, positions, triangles, p.material))
    normals = {k: g.vertex_normals(w.positions, w.triangles) for k, (_, w) in welded.items()}
    rings = {k: g.neighbours(w.positions.shape[0], w.triangles) for k, (_, w) in welded.items()}
    body_marks = landmark_points(marks)
    before = girths(_surface_cloud(parts, base), marks, centre_x=marks.centre_x)
    targets: list[MorphTarget] = []
    results: list[RegionResult] = []
    for region in profile.regions:
        template = profile.templates[region.template_id]
        anchor = locate(template.anchor, marks)
        if anchor is None:
            results.append(RegionResult(region.key, template.id, False,
                                        f"her landmarks cannot place {template.anchor}"))
            continue
        scale = _scale(template, waist_width_m)
        deltas, count, residual, why = {}, 0, 0.0, ""
        for part in parts:
            owner, wpart = welded[part.accessor]
            delta, n, res, reason = region_delta(wpart, normals[part.accessor], rings[part.accessor],
                                                 template, region, anchor.position, anchor.forward,
                                                 body_marks, scale)
            if n >= MIN_REGION_VERTICES and not reason:
                deltas[part.accessor] = delta[owner]
                count += n
                residual = max(residual, res)
            elif not why:
                why = reason
        if not deltas:
            results.append(RegionResult(region.key, template.id, False, why or "not placed"))
            continue
        trial = {k: render[k] + deltas.get(k, 0.0) for k in render}
        after = girths(_surface_cloud(parts, trial), marks, centre_x=marks.centre_x)
        change = {k: abs(after[k] - before[k]) / before[k] for k in before if k in after and before[k] > 0}
        broken = sorted(k for k in region.preserve if change.get(k, 0.0) > MAX_MEASUREMENT_CHANGE)
        if broken:
            results.append(RegionResult(region.key, template.id, False,
                                        f"would change her {', '.join(broken)} by more than "
                                        f"{MAX_MEASUREMENT_CHANGE:.1%}; dropped so her garments keep "
                                        "their size"))
            continue
        render = trial
        biggest = 0.0
        for accessor, delta in deltas.items():
            moved = np.flatnonzero(np.linalg.norm(delta, axis=1) > EPSILON_M)
            if not moved.size:
                continue
            biggest = max(biggest, float(np.linalg.norm(delta[moved], axis=1).max()))
            targets.append(MorphTarget(
                name="Body" + region.key[:1].upper() + region.key[1:], accessor=accessor,
                count=base[accessor].shape[0], indices=moved.astype(np.uint32),
                deltas=delta[moved].astype(np.float32), default_weight=region.default_weight))
        results.append(RegionResult(region.key, template.id, True, vertices=count,
                                    max_offset_mm=biggest * 1000, registration_mm=residual * 1000,
                                    measurements={k: round(v, 5) for k, v in change.items()}))
    return render, targets, results


__all__ = ["MAX_MEASUREMENT_CHANGE", "MIN_REGION_VERTICES", "MorphTarget", "RegionResult", "build_regions",
           "girths", "region_delta"]
