"""L8/L9. The fit report's ``lingerie`` block: each piece's elastic edges and its rules.

Mirrors ``wardrobe.hosiery.report``: built once after every garment is fitted, absent
from a job with no lingerie piece (so such a job's report is what it always was), and
its failed rules are warnings in the report's own list, never errors.
"""

from __future__ import annotations

import logging

from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.lingerie import elastic as elastics
from wardrobe.lingerie.validate import rules_for

logger = logging.getLogger(__name__)


def build(context) -> dict | None:
    layers = [layer for layer in context.built
              if (layer.artifact.procedural_kind or layer.plan.category) in LINGERIE_KINDS]
    if not layers:
        return None
    try:
        edges = elastics.measure(context)
    except Exception as exc:  # noqa: BLE001 - a measurement must not take the look down
        logger.warning("elastic measurement failed: %s", exc)
        edges = []
        context.warn(f"lingerie: elastic tension not measured ({type(exc).__name__})")
    hips = context.measurements.bone_positions.get("hips")
    centre_x = float(hips[0]) if hips is not None else 0.0
    pieces = []
    for layer in layers:
        kind = layer.artifact.procedural_kind or layer.plan.category
        own = [e for e in edges if e.piece == layer.plan.name]
        rules = rules_for(kind, layer.mesh, own, centre_x)
        tension = [e.to_dict() for e in own]
        piece = {"name": layer.plan.name, "kind": kind, "elastics": tension, "rules": rules}
        # RL4. Figures drafted from the reference library, with inputs and provenance; absent otherwise.
        if layer.mesh.metadata.get("lingerieReferences"):
            piece["references"] = layer.mesh.metadata["lingerieReferences"]
        pieces.append(piece)
    rows = [r for piece in pieces for r in piece["rules"]]
    warned = [r for r in rows if r["status"] != "pass"]
    return {"pieces": pieces, "rulesChecked": len(rows), "rulesWarned": len(warned),
            "warnings": [_say(r) for r in warned]}


def _say(row: dict) -> str:
    low, high = (row["spec"] + [None, None])[:2] if isinstance(row["spec"], list) else (None, None)
    bound = (f"{low}–{high}" if low is not None and high is not None
             else f"≤ {high}" if high is not None else f"≥ {low}")
    unit = f" {row['unit']}" if row.get("unit") else ""
    return f"{row['id']} is {row['value']}{unit}, expected {bound}{unit}"


__all__ = ["build"]
