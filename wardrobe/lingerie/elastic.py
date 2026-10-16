"""L8. Elastic tension: how hard each elastic edge of a lingerie piece pulls on her, per pose.

A brief's waist and leg openings and a bra's underband are elastics sewn to an edge,
cut shorter than the edge (``ElasticSpec.cut_ratio``): stretched on the flat garment,
stretched more on the body, and stretched differently again when she sits. Before L8
the edges were only named (``elastic-brief-leg`` sections, ``waist_elastic`` in the
spec, naming a library that did not exist); "too tight" and "gaping" had no number.

**Worn length is measured on her, not on the garment.** The fitted edge is laid on her
skin at rest (each edge point takes the nearest point of her skin, sampled about every
centimetre across her triangles, and its height above it), and carried into each pose
on her skin: the posed position of that same point of skin, out along its posed normal
by the same height. The garment's own skinned vertices are not used: skinning alone
pinches and collapses at a bent hip, which is why the hosiery straps are measured over
her posed body too (``hosiery.suspender_straps.taut_length``).

    pattern length   the edge on the fitted garment, standing (what the elastic is sewn to)
    rest length      cut_ratio × pattern length (the elastic, relaxed)
    worn length      the edge on her in that pose
    strain           worn / rest − 1
    force            ElasticSpec.force(strain), newtons over its full width
    pressure         T / (r · w), Laplace's law: r = worn / 2π, w = the elastic's width

The force curves are typical of their class (picot-edge lingerie elastic, plush-backed
underband), not a supplier's measured lot: a production style replaces them with the
lot's own, and every number here moves with it. Thresholds are the plan's §5 and are
reported, not enforced (L9 decides what they mean).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from wardrobe.lingerie.contract import ElasticSpec

#: The elastics the specs name (``BriefSpec.waist_elastic`` ...). Force in newtons over the
#: full width at each strain.
ELASTICS: dict[str, ElasticSpec] = {
    "picot-8": ElasticSpec("picot-8", 8.0, ((0.0, 0.0), (0.1, 0.7), (0.2, 1.35), (0.5, 3.0), (1.0, 5.4)),
                           cut_ratio=0.90, thickness_mm=0.9),
    "picot-10": ElasticSpec("picot-10", 10.0, ((0.0, 0.0), (0.1, 1.0), (0.2, 1.9), (0.5, 4.2), (1.0, 7.5)),
                            cut_ratio=0.90, thickness_mm=1.0),
    "band-12": ElasticSpec("band-12", 12.0, ((0.0, 0.0), (0.1, 1.5), (0.2, 2.8), (0.3, 4.0), (0.6, 7.2)),
                           cut_ratio=0.82, thickness_mm=1.4),
    "strap-10": ElasticSpec("strap-10", 10.0, ((0.0, 0.0), (0.1, 1.8), (0.2, 3.4), (0.5, 7.6)),
                            cut_ratio=1.0, thickness_mm=1.2),
}

#: Where each kind of edge is expected to sit (LINGERIE_UPGRADE_PLAN §5): strain standing,
#: pressure standing / seated (kPa), and the strain below which it gapes in any pose.
LIMITS: dict[str, dict] = {
    "waist": {"strainStand": (0.05, 0.15), "pressureStand": (0.4, 1.5), "gapeBelow": -0.02},
    "leg": {"strainStand": (0.03, 0.12), "pressureSitMax": 1.5, "gapeBelow": -0.02},
    "underband": {"strainStand": (0.10, 0.25), "gapeBelow": -0.02},
}

POSES = ("stand", "walk", "sit")
#: How far round her each edge's skin is sampled for, metres.
SKIN_SPACING_M = 0.01
REGION_MARGIN_M = 0.06


def elastic(name: str | None) -> ElasticSpec:
    return ELASTICS.get(str(name or ""), ELASTICS["picot-10"])


@dataclass
class FittedElasticEdge:
    """One elastic edge after fitting: its lengths, strain, force and pressure in each pose."""

    name: str
    kind: str  # waist | leg | underband
    piece: str
    spec: ElasticSpec
    pattern_length: float
    worn: dict[str, float] = field(default_factory=dict)

    @property
    def rest_length(self) -> float:
        return self.spec.cut_ratio * self.pattern_length

    def strain(self, pose: str) -> float:
        return self.worn[pose] / max(self.rest_length, 1e-9) - 1.0

    def force(self, pose: str) -> float:
        return self.spec.force(self.strain(pose))

    def pressure_kpa(self, pose: str) -> float:
        radius = self.worn[pose] / (2.0 * math.pi)
        return self.force(pose) / max(radius * self.spec.width_mm / 1000.0, 1e-9) / 1000.0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "piece": self.piece, "elastic": self.spec.name,
            "widthMm": self.spec.width_mm, "cutRatio": self.spec.cut_ratio,
            "patternLengthM": round(self.pattern_length, 4), "restLengthM": round(self.rest_length, 4),
            "wornM": {p: round(v, 4) for p, v in self.worn.items()},
            "strain": {p: round(self.strain(p), 4) for p in self.worn},
            "forceN": {p: round(self.force(p), 3) for p in self.worn},
            "pressureKpa": {p: round(self.pressure_kpa(p), 3) for p in self.worn},
        }


# ----------------------------------------------------------------------
# which edges a fitted piece has
# ----------------------------------------------------------------------
def edges_of(mesh, kind: str, block: dict) -> list[tuple[str, str, list[int], ElasticSpec]]:
    """(name, kind, closed vertex loop, elastic) for each elastic edge the block recorded."""
    from wardrobe.lingerie.specs import parse_block

    parsed = parse_block(kind, block)
    out = []
    brief = mesh.metadata.get("lingerieBrief")
    if brief:
        spec = parsed.brief
        if kind != "bodysuit-block" and brief.get("waist"):
            # A bodysuit's top edge is its neckline, not a waist elastic.
            waist = elastic(getattr(spec, "waist_elastic", None))
            out.append(("waist", "waist", list(brief["waist"]), waist))
        for side, loop in (brief.get("legOpenings") or {}).items():
            out.append((f"leg-{side}", "leg", list(loop), elastic(getattr(spec, "leg_elastic", "picot-8"))))
    bra = mesh.metadata.get("lingerieBra")
    if bra and bra.get("bandRows"):
        bottom = [int(v) for v in bra["bandRows"][-1]]
        out.append(("underband", "underband", bottom,
                    elastic(getattr(parsed.bra, "band_elastic", None) or "band-12")))
    return out


def _loop_length(points: np.ndarray) -> float:
    closed = points if np.allclose(points[0], points[-1]) else np.vstack([points, points[:1]])
    return float(np.linalg.norm(np.diff(closed, axis=0), axis=1).sum())


# ----------------------------------------------------------------------
# her skin, at rest and in each pose, sample for sample
# ----------------------------------------------------------------------
def _skin(document, info, forward: float, pivots: dict, box: tuple[np.ndarray, np.ndarray]) -> dict:
    """Her skin near the edges sampled at rest, and the same samples in each pose."""
    from wardrobe.hosiery.poses import node_table, posed_primitive, surface_samples
    from wardrobe.hosiery.previews import _normals, _same_samples, _triangles

    tables = {pose: node_table(document, info, pose, forward, pivots) for pose in POSES}
    rest_p, rest_n, posed = [], [], {pose: ([], []) for pose in POSES}
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        if ((node.get("extras") or {}).get("wardrobeForge") or {}).get("kind") in ("garment", "bodyArt"):
            continue
        sources = {p["attributes"]["POSITION"] for p in document.meshes[node["mesh"]].get("primitives", [])
                   if p.get("attributes", {}).get("POSITION") is not None}
        for source in sources:
            primitive = next(p for p in document.meshes[node["mesh"]]["primitives"]
                             if p["attributes"].get("POSITION") == source)
            if posed_primitive(document, node, primitive, tables["stand"], normals=False) is None:
                continue  # not skinned: not her body
            rest = document.read_accessor(source).astype(np.float64)[:, :3]
            triangles = _triangles(document, node, source)
            centre = rest[triangles].mean(axis=1) if len(triangles) else np.zeros((0, 3))
            near = np.all((centre >= box[0] - REGION_MARGIN_M) & (centre <= box[1] + REGION_MARGIN_M), axis=1)
            triangles = triangles[near]
            if not len(triangles):
                continue
            a, na = surface_samples(rest, _normals(rest, document, node, source), triangles, SKIN_SPACING_M)
            rest_p.append(a)
            rest_n.append(na)
            for pose in POSES:
                points = posed_primitive(document, node, primitive, tables[pose], normals=False)[0]
                b, nb = _same_samples(rest, points, _normals(points, document, node, source), triangles,
                                      SKIN_SPACING_M)
                posed[pose][0].append(b)
                posed[pose][1].append(nb)
    if not rest_p:
        return {}
    return {"rest": (np.vstack(rest_p), np.vstack(rest_n)),
            **{pose: (np.vstack(p), np.vstack(n)) for pose, (p, n) in posed.items()}}


def _follow(points: np.ndarray, skin: dict, pose: str) -> np.ndarray:
    """Carry rest points into ``pose`` on the skin under them, at their height above it."""
    rest_p, rest_n = skin["rest"]
    posed_p, posed_n = skin[pose]
    out = np.zeros_like(points)
    for start in range(0, len(points), 64):
        chunk = points[start:start + 64]
        nearest = np.argmin(((chunk[:, None, :] - rest_p[None, :, :]) ** 2).sum(axis=2), axis=1)
        height = np.maximum(((chunk - rest_p[nearest]) * rest_n[nearest]).sum(axis=1), 0.0)
        out[start:start + 64] = posed_p[nearest] + posed_n[nearest] * height[:, None]
    return out


def measure(context) -> list[FittedElasticEdge]:
    """Every elastic edge of every lingerie piece this job fitted, measured in each pose."""
    from wardrobe.hosiery.fit import forward as facing
    from wardrobe.lingerie import LINGERIE_KINDS

    pieces = []
    for layer in context.built:
        kind = layer.artifact.procedural_kind or layer.plan.category
        if kind not in LINGERIE_KINDS:
            continue
        block = (layer.artifact.metadata.get("lingerie") or {})
        for name, edge_kind, loop, spec in edges_of(layer.mesh, kind, block):
            points = layer.mesh.positions.astype(np.float64)[np.asarray(loop, dtype=int)]
            pieces.append((layer.plan.name, name, edge_kind, points, spec))
    if not pieces or context.document is None or context.info is None:
        return []
    every = np.vstack([p for *_, p, _ in pieces])
    skin = _skin(context.document, context.info, facing(context), context.measurements.bone_positions,
                 (every.min(axis=0), every.max(axis=0)))
    if not skin:
        return []
    out = []
    for piece, name, edge_kind, points, spec in pieces:
        edge = FittedElasticEdge(name=name, kind=edge_kind, piece=piece, spec=spec,
                                 pattern_length=_loop_length(points))
        for pose in POSES:
            edge.worn[pose] = _loop_length(_follow(points, skin, pose))
        out.append(edge)
    return out


__all__ = ["ELASTICS", "LIMITS", "FittedElasticEdge", "edges_of", "elastic", "measure"]
