"""RB3. Calibrate the anatomical reference bodies and record their modifiers.

    python tools/anatomy/calibrate_reference.py [size-id ...]

Each size's MakeHuman modifiers are solved against its ANSUR II targets
(``wardrobe.anatomy.reference.calibrate``) and written to ``assets/anatomy/reference-bodies.json``
with the dimensions the finished body measures. Building a body from that record is fast and
deterministic; the tests rebuild from it and re-measure, so a record that no longer reproduces
its numbers fails.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy import reference as R  # noqa: E402


def main(argv: list[str]) -> int:
    sizes = argv or list(R.reference_sizes()["sizes"])
    existing = json.loads(R.BODIES_PATH.read_text()) if R.BODIES_PATH.exists() else {"bodies": {}}
    for size_id in sizes:
        started = time.time()

        def log(it, rms, _d, size_id=size_id):
            print(f"  {size_id} iteration {it}: rms {rms:.2f}")

        record = R.calibrate(size_id, log=log)
        record["calibrationSeconds"] = round(time.time() - started, 1)
        existing["bodies"][size_id] = record
        print(
            f"{size_id}: done in {record['calibrationSeconds']} s; "
            f"outside tolerance: {record['outsideTolerance'] or 'none'}"
        )
    existing.update(
        {
            "schema": "wardrobe.anatomy.referenceBodies.v1",
            "template": "assets/anatomy/makehuman-provenance.json",
            "sizes": "assets/anatomy/reference-sizes.json",
            "subdivisionLevels": R.LEVELS,
            "tolerances": R.TOLERANCE,
            "unmodelled": R.UNMODELLED,
            "anatomy": R.ANATOMY,
            "shapePriors": R.SHAPE_PRIORS,
        }
    )
    R.BODIES_PATH.write_text(json.dumps(existing, indent=1) + "\n")
    # The records are of the template surface; the pelvic outlet is fitted to it and must follow.
    print("now run tools/anatomy/fit_pelvis.py: a stored outlet fitted to the old surface is refused")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
