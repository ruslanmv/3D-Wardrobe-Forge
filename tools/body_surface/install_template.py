#!/usr/bin/env python3
"""BS1. Install a body-surface template into the server's allowlist, with its provenance.

    python tools/body_surface/install_template.py FIELD.json --id navel/v1 --region navel \\
        --anchor navel --radius-mm 36 --license CC0-1.0 --source "…" --author "…" \\
        --no-real-person-scan [--landmarks LANDMARKS.json] [--reference-waist-mm 260]

    python tools/body_surface/install_template.py --procedural navel   # the shipped CC0 navel

``FIELD.json`` is a rows × cols × 3 array of (dn, du, dv) in metres over the chart
[-radius, radius]²: dn along her surface normal (negative is into her), du across her, dv up
her. It must be zero on the chart's edge, so the region meets her untouched skin with no step.

What the tool refuses, and why:

* a licence not on ``wardrobe.body_surface.library.LICENSES`` — SMPL, SMPL-X and STAR model data
  are research-only and are deliberately absent;
* a template without ``--no-real-person-scan`` — a scan of a real person is biometric data
  (GDPR Art. 9) and needs consent and review this tool cannot record;
* a field that is not zero on its edge, or larger than the template itself.

It writes ``assets/body_surface/templates/<id with / as ->.json`` with the field's SHA-256 in
the provenance. The server re-hashes it on load and refuses a template edited afterwards.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.body_surface.library import (  # noqa: E402
    ANCHORS,
    LICENSES,
    TEMPLATE_SCHEMA,
    _sha256_field,
    load_template,
)

TEMPLATES = ROOT / "assets" / "body_surface" / "templates"


def procedural_navel(radius_m: float = 0.036, cells: int = 37) -> np.ndarray:
    """A soft, slightly upright hollow with a low rim: the shipped navel, authored here (CC0).

    dn(r) = −depth·e^{−(r/0.22R)²} + rim·e^{−((r−0.34R)/0.1R)²}, tapered by (1−r²)² to zero
    at the edge, with r measured on an ellipse 1.35× taller than wide. The hollow is about 8 mm
    across; the 36 mm support is the skin it fades into, which is what lets a VRoid torso (13–15 mm
    edges) hold it at all. Depth 3.5 mm, rim 0.6 mm: a gentle dimple, all her mesh can express.
    """
    axis = np.linspace(-radius_m, radius_m, cells)
    u, v = np.meshgrid(axis, axis)  # rows: v, cols: u
    r = np.sqrt(u ** 2 + (v / 1.35) ** 2) / radius_m
    dn = -0.0035 * np.exp(-(r / 0.22) ** 2) + 0.0006 * np.exp(-((r - 0.34) / 0.1) ** 2)
    taper = np.clip(1 - r ** 2, 0, 1) ** 2
    field = np.zeros((cells, cells, 3))
    field[:, :, 0] = dn * taper
    field[0, :] = field[-1, :] = field[:, 0] = field[:, -1] = 0.0
    return np.round(field, 7)


def install(field: np.ndarray, *, template_id: str, region: str, anchor: str, radius_m: float,
            license_id: str, source: str, author: str, landmarks: dict, reference_waist_m: float,
            notes: str = "", templates_dir: Path = TEMPLATES) -> Path:
    if license_id not in LICENSES:
        raise SystemExit(f"licence {license_id!r} is not allowed; allowed: {', '.join(sorted(LICENSES))}")
    if anchor not in ANCHORS:
        raise SystemExit(f"anchor must be one of {', '.join(sorted(ANCHORS))}")
    data = {
        "schema": TEMPLATE_SCHEMA,
        "id": template_id,
        "region": region,
        "anchor": anchor,
        "radiusM": radius_m,
        "referenceWaistM": reference_waist_m,
        "landmarks": landmarks,
        "field": np.asarray(field, dtype=np.float64).round(7).tolist(),
    }
    data["provenance"] = {
        "source": source,
        "author": author,
        "license": license_id,
        "containsRealPersonScan": False,
        "installedAt": dt.date.today().isoformat(),
        "notes": notes,
        "sha256": _sha256_field(data),
    }
    templates_dir.mkdir(parents=True, exist_ok=True)
    path = templates_dir / (template_id.replace("/", "-") + ".json")
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    load_template(path)  # the server's own check, before anyone relies on the file
    return path


NAVEL_LANDMARKS = {
    "centre": {"uv": [0.0, 0.0]},
    "top": {"uv": [0.0, 0.011]},
    "bottom": {"uv": [0.0, -0.011]},
    "left": {"uv": [-0.008, 0.0]},
    "right": {"uv": [0.008, 0.0]},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("field", nargs="?", type=Path)
    parser.add_argument("--procedural", choices=["navel"])
    parser.add_argument("--id")
    parser.add_argument("--region")
    parser.add_argument("--anchor")
    parser.add_argument("--radius-mm", type=float)
    parser.add_argument("--reference-waist-mm", type=float, default=260.0)
    parser.add_argument("--license")
    parser.add_argument("--source")
    parser.add_argument("--author")
    parser.add_argument("--landmarks", type=Path)
    parser.add_argument("--notes", default="")
    parser.add_argument("--no-real-person-scan", action="store_true",
                        help="state that the template is not derived from a scan of a real person")
    args = parser.parse_args()
    if args.procedural == "navel":
        path = install(procedural_navel(), template_id="navel/v1", region="navel", anchor="navel",
                       radius_m=0.036, license_id="CC0-1.0", author="3D-Wardrobe-Forge contributors",
                       source="authored procedurally in tools/body_surface/install_template.py "
                              "(procedural_navel)",
                       landmarks=NAVEL_LANDMARKS, reference_waist_m=0.26,
                       notes="analytic dimple; no scan, no third-party asset")
        print("installed", path.relative_to(ROOT))
        return 0
    missing = [n for n in ("field", "id", "region", "anchor", "radius_mm", "license", "source", "author")
               if getattr(args, n) is None]
    if missing:
        raise SystemExit("missing: " + ", ".join(missing))
    if not args.no_real_person_scan:
        raise SystemExit("refused: pass --no-real-person-scan to state the template is not a scan of a real "
                         "person (scans need consent and review this tool cannot record)")
    field = np.asarray(json.loads(args.field.read_text(encoding="utf-8")), dtype=np.float64)
    landmarks = json.loads(args.landmarks.read_text(encoding="utf-8")) if args.landmarks else {
        "centre": {"uv": [0.0, 0.0]}}
    path = install(field, template_id=args.id, region=args.region, anchor=args.anchor,
                   radius_m=args.radius_mm / 1000, license_id=args.license, source=args.source,
                   author=args.author,
                   landmarks=landmarks, reference_waist_m=args.reference_waist_mm / 1000, notes=args.notes)
    print("installed", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
