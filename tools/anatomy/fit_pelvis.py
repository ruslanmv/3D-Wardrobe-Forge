"""AN-A2. Fit the atlas's pelvic outlet onto every reference body and store the result.

    python tools/anatomy/fit_pelvis.py [size ...]

For each size (all four by default) the body is built from its recorded modifiers, the scan
imported by ``import_hra.py`` is fitted onto it (``wardrobe.anatomy.pelvis.fit``), and the
displacement is stored in ``assets/anatomy/pelvic-outlet.npz`` with a hash of the surface it was
fitted to. Re-run after ``calibrate_reference.py``: ``pelvis.apply`` refuses a fit whose surface
has changed. The fit's own numbers, and what the body measures with the outlet against without
it, go to ``assets/anatomy/pelvic-outlet.json``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy import pelvis as P  # noqa: E402
from wardrobe.anatomy import reference as R  # noqa: E402
from wardrobe.anatomy.topology import check  # noqa: E402

REPORT = ROOT / "assets" / "anatomy" / "pelvic-outlet.json"


def main(argv: list[str]) -> int:
    sizes = argv or list(R.reference_bodies()["bodies"])
    arrays: dict[str, np.ndarray] = {}
    report = json.loads(REPORT.read_text()) if REPORT.exists() and argv else {}
    if P.OUTLET_PATH.exists() and argv:  # fitting some sizes keeps the others
        with np.load(P.OUTLET_PATH) as old:
            arrays = {k: old[k] for k in old.files if k != "sizes"}
    for size_id in sizes:
        started = time.time()
        record = R.reference_bodies()["bodies"][size_id]
        V, T, J = R.build(record["modifiers"])
        before = R.measure_body(V, T, J)
        made = P.fit(V, T, np.asarray(before.landmarks["crotch"]))
        arrays[f"{size_id}/indices"] = made.indices.astype(np.int32)
        arrays[f"{size_id}/delta"] = made.delta.astype(np.float32)
        arrays[f"{size_id}/stamp"] = np.array(P.stamp(V, made.indices))
        after_V = V.copy()
        after_V[made.indices] += made.delta.astype(np.float32).astype(np.float64)
        after = R.measure_body(after_V, T, J)
        topology = check(after_V, T).to_dict()
        report[size_id] = {
            "fit": made.report,
            "topology": topology,
            "measurementShiftMm": {
                k: round(after.values[k] - before.values[k], 1)
                for k in after.values
                if abs(after.values[k] - before.values[k]) >= 0.05
            },
            "seconds": round(time.time() - started, 1),
        }
        print(size_id, json.dumps(report[size_id]), flush=True)
    sizes_all = sorted({k.split("/")[0] for k in arrays})
    np.savez_compressed(P.OUTLET_PATH, sizes=np.array(sizes_all), **arrays)
    report = {k: report[k] for k in sorted(report)}
    report["source"] = {
        "patch": "assets/anatomy/hra-pelvis.npz",
        "provenance": "assets/anatomy/hra-provenance.json",
        "attribution": P.provenance()["attribution"],
    }
    REPORT.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
