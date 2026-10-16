"""L9. Garment-specific validation: the rules a lingerie piece is checked against, per type.

The fit report already says whether a look is a valid VRM, clears her body, went on
her skin and in the right layer order (PB2). None of that says whether a brief's waist
elastic gapes when she sits, whether a bra's underband is level, or whether its cups are
symmetric — the things a fit technician checks on a fit model. These are those checks,
with the plan's §5 thresholds (LINGERIE_UPGRADE_PLAN), each as one row:

    {"id": "brief.waist.strain.stand", "value": 0.111, "spec": [0.05, 0.15], "status": "pass"}

Rows come from what the blocks record about themselves (``lingerieBrief``,
``lingerieBra``) and from the elastic edges measured on her in each pose (L8). A row
that fails is a **warning**, not an error: the plan rolls the thresholds out as warnings
first and promotes them to errors only once they are tuned on the real avatars and the
fit forms, as the hosiery thresholds were. So a rule never changes ``passed``.
"""

from __future__ import annotations

import numpy as np

from wardrobe.lingerie.elastic import LIMITS, FittedElasticEdge

#: Millimetre tolerances from §5.
GUSSET_MIDLINE_MM = 5.0
COVERAGE_TOLERANCE = 0.02
UNDERBAND_LEVEL_MM = 10.0
CUP_SYMMETRY_MM = 5.0
STRAP_STRETCH_MAX = 0.08
STRAP_SLACK_MIN = -0.05


def _row(rule: str, value: float, spec, ok: bool, unit: str = "") -> dict:
    return {"id": rule, "value": round(float(value), 4), "spec": spec, "unit": unit,
            "status": "pass" if ok else "warn"}


def _between(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def elastic_rules(edge: FittedElasticEdge, prefix: str) -> list[dict]:
    limits = LIMITS[edge.kind]
    key = f"{prefix}.{edge.name}"
    rows = []
    if "strainStand" in limits:
        rows.append(_row(f"{key}.strain.stand", edge.strain("stand"), list(limits["strainStand"]),
                         _between(edge.strain("stand"), limits["strainStand"])))
    if "pressureStand" in limits:
        rows.append(_row(f"{key}.pressure.stand", edge.pressure_kpa("stand"), list(limits["pressureStand"]),
                         _between(edge.pressure_kpa("stand"), limits["pressureStand"]), "kPa"))
    if "pressureSitMax" in limits and "sit" in edge.worn:
        rows.append(_row(f"{key}.pressure.sit", edge.pressure_kpa("sit"), [0.0, limits["pressureSitMax"]],
                         edge.pressure_kpa("sit") <= limits["pressureSitMax"], "kPa"))
    least = min(edge.strain(p) for p in edge.worn)
    rows.append(_row(f"{key}.gape", least, [limits["gapeBelow"], None], least >= limits["gapeBelow"]))
    return rows


def brief_rules(mesh, centre_x: float) -> list[dict]:
    record = mesh.metadata.get("lingerieBrief") or {}
    rows = []
    gusset = [v for row in record.get("gusset") or [] for v in row]
    if gusset:
        x = float(mesh.positions[np.asarray(gusset, dtype=int), 0].mean())
        off = abs(x - centre_x) * 1000.0
        rows.append(_row("brief.gusset.midline", off, [0.0, GUSSET_MIDLINE_MM], off <= GUSSET_MIDLINE_MM,
                         "mm"))
    spec, measures = record.get("spec") or {}, record.get("measures") or {}
    for side in ("front", "back"):
        wanted, got = spec.get(f"{side}_coverage"), measures.get(f"{side}Coverage")
        if isinstance(wanted, int | float) and isinstance(got, int | float):
            rows.append(_row(f"brief.coverage.{side}", got,
                             [round(wanted - COVERAGE_TOLERANCE, 3), round(wanted + COVERAGE_TOLERANCE, 3)],
                             abs(got - wanted) <= COVERAGE_TOLERANCE))
    return rows


def bra_rules(mesh, centre_x: float) -> list[dict]:
    record = mesh.metadata.get("lingerieBra") or {}
    rows = []
    band = record.get("bandRows") or []
    if band:
        bottom = mesh.positions[np.asarray(band[-1], dtype=int)].astype(np.float64)
        level = (float(bottom[:, 1].max()) - float(bottom[:, 1].min())) / 2.0 * 1000.0
        rows.append(_row("bra.underband.level", level, [0.0, UNDERBAND_LEVEL_MM],
                         level <= UNDERBAND_LEVEL_MM, "mm"))
    cups = record.get("cups") or {}
    if {"left", "right"} <= set(cups):
        left, right = (np.asarray(cups[s]["apex"], dtype=np.float64) for s in ("left", "right"))
        height = abs(left[1] - right[1]) * 1000.0
        across = abs((left[0] + right[0]) - 2.0 * centre_x) * 1000.0
        worst = max(height, across)
        rows.append(_row("bra.cups.symmetry", worst, [0.0, CUP_SYMMETRY_MM], worst <= CUP_SYMMETRY_MM, "mm"))
    for side, strap in (record.get("straps") or {}).items():
        stretch = strap.get("stretch") or {}
        if not stretch:
            continue
        most, least = max(stretch.values()), min(stretch.values())
        rows.append(_row(f"bra.strap-{side}.stretch", most, [None, STRAP_STRETCH_MAX],
                         most <= STRAP_STRETCH_MAX))
        rows.append(_row(f"bra.strap-{side}.slack", least, [STRAP_SLACK_MIN, None], least >= STRAP_SLACK_MIN))
    return rows


def rules_for(kind: str, mesh, edges: list[FittedElasticEdge], centre_x: float) -> list[dict]:
    """Every rule for one fitted lingerie piece."""
    prefix = {"brief-block": "brief", "bra-block": "bra", "bodysuit-block": "bodysuit"}.get(kind, kind)
    rows = []
    if mesh.metadata.get("lingerieBrief"):
        rows += [{**r, "id": r["id"].replace("brief.", f"{prefix}.", 1)} for r in brief_rules(mesh, centre_x)]
    if mesh.metadata.get("lingerieBra"):
        rows += bra_rules(mesh, centre_x)
    for edge in edges:
        rows += elastic_rules(edge, prefix)
    return rows


__all__ = ["bra_rules", "brief_rules", "elastic_rules", "rules_for"]
