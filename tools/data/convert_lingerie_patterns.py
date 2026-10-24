"""RL2. Normalize the vendored lingerie references into JSON the generator reads.

    python tools/data/convert_lingerie_patterns.py           # write the JSON beside each source
    python tools/data/convert_lingerie_patterns.py --check   # fail if a written JSON is stale

Reads only the byte-for-byte copies tools/data/fetch_lingerie_sources.py keeps, and never
runs them: BraCupPattern's Python is read with ``ast``, Uma's option table with a strict
pattern, GarmentCode's YAML with a YAML reader. Every number in the output is one the
source states; nothing is filled in. A formula the generator applies is matched against the
source's own line, so if upstream changes the draft the conversion stops instead of carrying
a rule the source no longer has.

Output (all lengths in mm):

* patterns/bracuppattern/bracuppattern-cup.json — the cup outline at the reference size, the
  grading rule and the size table;
* patterns/freesewing-uma/uma-draft.json — Uma's options (default, min, max) and the gusset
  formulas;
* measurements/garmentcode/garmentcode-mean-female.json — the body measurements in mm.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "assets" / "reference" / "lingerie"
LOCK = BASE / "sources.lock.json"


def _provenance(source_id: str, path: str) -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    source = next(s for s in lock["sources"] if s["id"] == source_id)
    entry = next(f for f in source["files"] if f["path"].endswith(path))
    return {
        "source": source_id,
        "license": source["license"],
        "commit": source["version"].get("commit"),
        "file": entry["path"],
        "sha256": entry["sha256"],
        "attribution": source["attribution"],
    }


def _literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value
    raise SystemExit(f"bracuppattern: no top-level {name!r} in the vendored source")


def bracuppattern() -> dict:
    path = BASE / "patterns" / "bracuppattern" / "generate_site.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    points = []
    for call in _literal(tree, "pattern_points").elts:
        fields = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
        points.append(
            {
                "origin": fields["origin"],
                "controlCcw": fields["control_ccw"],
                "controlCw": fields["control_cw"],
            }
        )
    base_cm = ast.literal_eval(_literal(tree, "line_length_base"))
    step_cm = ast.literal_eval(_literal(tree, "line_length_step"))
    sizes = []
    for call in _literal(tree, "cup_sizes").elts:
        fields = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
        low, high = (float(v) * 10.0 for v in re.findall(r"([\d.]+)cm", fields["over_breast_measurement"]))
        number = int(fields["size_no"])
        line = (base_cm + (number - 1) * step_cm) * 10.0
        sizes.append(
            {
                "size": number,
                "overBreastMinMm": round(low, 1),
                "overBreastMaxMm": round(high, 1),
                "line1Mm": round(line, 2),
            }
        )
    reference = 4
    ref_line = next(s["line1Mm"] for s in sizes if s["size"] == reference)
    for s in sizes:
        s["scale"] = round(s["line1Mm"] / ref_line, 6)
    return {
        "schema": "forge.reference.cup-outline/1",
        "units": "mm",
        "what": "One cup panel outline: a closed path of cubic Bezier segments (origin, handles), drawn "
        "at the reference "
        "size; every other size is this outline scaled by line1Mm / reference line1Mm.",
        "referenceSize": reference,
        "points": points,
        "grading": {
            "rule": "linear scale by line 1",
            "line1AtSize1Mm": round(base_cm * 10.0, 2),
            "line1StepMm": round(step_cm * 10.0, 2),
            "line1Meaning": "not documented by the source",
        },
        "sizes": sizes,
        "provenance": _provenance("bracuppattern", "generate_site.py"),
    }


#: The lines of Uma's draft whose formulas uma-draft.json carries, exactly as the source has them.
UMA_FORMULAS = {
    "gussetLength": "const gussetLength = measurements.seat * options.gussetLength * stretch.y",
    "gussetWidth": "measurements.waistToUpperLeg *\n        mergedOptions.gussetWidth *\n        2 *\n"
    "        stretchToScale(mergedOptions.xStretch),",
    "stretch": "x: utils.stretchToScale(options.xStretch),",
}


def uma() -> dict:
    path = BASE / "patterns" / "freesewing-uma" / "base.mjs"
    text = path.read_text(encoding="utf-8")
    for name, line in UMA_FORMULAS.items():
        if line not in text:
            raise SystemExit(
                f"freesewing-uma: the {name} formula is no longer in {path.name}; re-inspect the source"
            )
    block = text[text.index("  options: {") : text.index("  draft: draftUmaBase")]
    options = {}
    for name, kind, value, low, high in re.findall(
        r"(\w+): \{\s*(pct|deg): (-?[\d.]+),\s*min: (-?[\d.]+),\s*max: (-?[\d.]+)", block
    ):
        scale = 100.0 if kind == "pct" else 1.0
        options[name] = {
            "unit": "fraction" if kind == "pct" else "deg",
            "default": float(value) / scale,
            "min": float(low) / scale,
            "max": float(high) / scale,
        }
    measurements = re.search(r"measurements: \[([^\]]*)\]", text).group(1)
    return {
        "schema": "forge.reference.brief-draft/1",
        "units": "mm",
        "what": "FreeSewing Uma's brief draft: options as fractions, and the gusset formulas the "
        "generator applies.",
        "measurements": [m.strip().strip("'\"") for m in measurements.split(",") if m.strip()],
        "options": options,
        "formulas": {
            "stretchToScale": "1 / (1 + stretch)",
            "gussetLengthMm": "seat * gussetLength * stretchToScale(yStretch)",
            "gussetWidthMm": "waistToUpperLeg * gussetWidth * 2 * stretchToScale(xStretch)",
            "sourceLines": UMA_FORMULAS,
        },
        "caveat": "Defaults are one designer's draft for stretch knit, not a population norm; the "
        "stretch options are "
        "negative ease chosen by the designer, not a fabric test result.",
        "provenance": _provenance("freesewing-uma", "base.mjs"),
    }


def garmentcode() -> dict:
    path = BASE / "measurements" / "garmentcode" / "mean_female.yaml"
    body = yaml.safe_load(path.read_text(encoding="utf-8"))["body"]
    angles = {"arm_pose_angle", "shoulder_incl", "hip_inclination"}
    return {
        "schema": "forge.reference.body-measurements/1",
        "units": "mm (angles in degrees)",
        "what": "GarmentCode's average female body (GarmentMeasurements' own body model, not SMPL), "
        "centimetres "
        "converted to millimetres. Definitions: docs/research/LINGERIE_MEASUREMENT_METHODS.md.",
        "measurements": {
            k: (round(float(v), 4) if k in angles else round(float(v) * 10.0, 2)) for k, v in body.items()
        },
        "provenance": _provenance("garmentcode", "mean_female.yaml"),
    }


OUTPUTS = {
    "patterns/bracuppattern/bracuppattern-cup.json": bracuppattern,
    "patterns/freesewing-uma/uma-draft.json": uma,
    "measurements/garmentcode/garmentcode-mean-female.json": garmentcode,
}


def main() -> int:
    formatter = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=formatter)
    parser.add_argument(
        "--check", action="store_true", help="fail if a written JSON differs from a fresh conversion"
    )
    args = parser.parse_args()
    stale = []
    for relative, build in OUTPUTS.items():
        text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
        target = BASE / relative
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != text:
                stale.append(relative)
        else:
            target.write_text(text, encoding="utf-8")
            print(f"wrote {relative}")
    for relative in stale:
        print(f"STALE {relative}: run tools/data/convert_lingerie_patterns.py", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
