"""RL4. Reference-drafted pattern figures: what a block takes from the reference library.

A template's brief block may ask for a figure to be drafted from a verified reference rather
than given as a constant (``BriefSpec.gusset_draft``). The reference is read from the
normalized library (``assets/reference/lingerie``, see docs/research/LINGERIE_REFERENCE_LIBRARY.md),
applied to her measured frame, and recorded on the mesh with its inputs and provenance, so a
fit report says where each number came from: her body, the reference, or the designer.

**freesewing-uma.** FreeSewing's Uma drafts the gusset from two body measurements:

    width  = waistToUpperLeg x gussetWidth x 2 / (1 + xStretch)
    length = seat x gussetLength / (1 + yStretch)

with the draft's defaults (gussetWidth 15%, gussetLength 12.7%) and the fabric's stretch
allowance. Her measurements are taken as FreeSewing defines them: ``seat`` is the girth
round the fullest part of her seat (her full-hip landmark), here the perimeter of her
measured outline there; ``waistToUpperLeg`` is measured at her side from the waist down to
the upper-leg girth "a bit below the crotch" — the bit is not given, so waist-to-crotch is
used and the width is a lower bound by that much.

The stretch allowance is the fabric's (``lingerie.fabric`` naming a class in
materials/fabrics.json); a class without one, or no fabric named, takes Uma's own defaults
and the record says so. Only the width changes the mesh: this block's gusset length is a
texture length (the gusset runs between seams fixed above her crotch), so the drafted length
is recorded and applied to the texture, not to the shape — see LINGERIE_PATTERN_ENGINE.md.
"""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "assets" / "reference" / "lingerie"
#: The gusset drafts a brief block may name.
GUSSET_DRAFTS = ("freesewing-uma",)


@cache
def _json(relative: str) -> dict:
    return json.loads((LIBRARY / relative).read_text(encoding="utf-8"))


def uma_draft() -> dict:
    return _json("patterns/freesewing-uma/uma-draft.json")


def fabric_class(name: str | None) -> dict | None:
    """The mechanical fabric class ``name`` (materials/fabrics.json), or None."""
    if not name:
        return None
    return next((c for c in _json("materials/fabrics.json")["classes"] if c["id"] == name), None)


def ellipse_perimeter(a: float, b: float) -> float:
    """Ramanujan's second approximation: within 0.04% for the aspect ratios of a body section."""
    h = ((a - b) / (a + b)) ** 2 if a + b > 0 else 0.0
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def stretch_allowance(fabric: str | None) -> dict:
    """(xStretch, yStretch) for the gusset draft, from the fabric's class or Uma's defaults, and why."""
    options = uma_draft()["options"]
    found = fabric_class(fabric)
    out = {}
    axes = (("x", "patternStretchCourse", "xStretch"), ("y", "patternStretchWale", "yStretch"))
    for axis, key, option in axes:
        value = (found or {}).get(key) or {}
        if value.get("value") is not None:
            out[axis] = {
                "value": float(value["value"]),
                "status": value["status"],
                "from": f"fabric {fabric}",
            }
        else:
            if found:
                reason = f"fabric {fabric} has none"
            else:
                reason = f"unknown fabric {fabric}" if fabric else "no fabric named"
            out[axis] = {
                "value": float(options[option]["default"]),
                "status": "designer-convention",
                "from": f"freesewing-uma {option} default ({reason})",
            }
    return out


def uma_gusset(frame, fabric: str | None = None) -> dict:
    """Uma's gusset width and length on her measured ``frame`` (wardrobe.lingerie.blocks.frame)."""
    draft = uma_draft()
    options = draft["options"]
    marks = frame.marks
    half_w, half_d, _cx, _cz = frame.outline(marks.full_hip_y)
    seat = ellipse_perimeter(half_w, half_d)
    to_upper_leg = max(float(marks.waist_y) - float(marks.crotch_y), 0.0)
    stretch = stretch_allowance(fabric)
    width = to_upper_leg * options["gussetWidth"]["default"] * 2 / (1 + stretch["x"]["value"])
    length = seat * options["gussetLength"]["default"] / (1 + stretch["y"]["value"])
    return {
        "draft": "freesewing-uma",
        "gussetWidthMm": round(width * 1000.0, 2),
        "gussetLengthMm": round(length * 1000.0, 2),
        "appliedTo": {
            "gussetWidthMm": "geometry",
            "gussetLengthMm": "texture only (seams fixed above her crotch)",
        },
        "inputs": {
            "seatMm": {
                "value": round(seat * 1000.0, 1),
                "kind": "body",
                "how": "perimeter of her measured outline at the full hip",
            },
            "waistToUpperLegMm": {
                "value": round(to_upper_leg * 1000.0, 1),
                "kind": "body",
                "how": "waist to crotch at her side; FreeSewing's is a little lower: a lower bound",
            },
            "gussetWidth": {"value": options["gussetWidth"]["default"], "kind": "reference"},
            "gussetLength": {"value": options["gussetLength"]["default"], "kind": "reference"},
            "xStretch": {**stretch["x"], "kind": "material"},
            "yStretch": {**stretch["y"], "kind": "material"},
        },
        "provenance": draft["provenance"],
    }


__all__ = [
    "GUSSET_DRAFTS",
    "ellipse_perimeter",
    "fabric_class",
    "stretch_allowance",
    "uma_draft",
    "uma_gusset",
]
