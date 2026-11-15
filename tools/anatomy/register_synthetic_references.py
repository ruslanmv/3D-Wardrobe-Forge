"""BE1. Record the exact bytes of Forge's synthetic adult reference bodies.

    python tools/anatomy/register_synthetic_references.py [--bodies ref-f-median ...] [--check]

A bare look needs a design clearance for its exact source file (``wardrobe.body_surface.eligibility``).
For a library character that is a person's review. For a reference body Forge generates itself
(MakeHuman's CC0 adult template calibrated to ANSUR II adult women, faceless, without hair) there
is no character design to review; what has to be established instead is that the file *is* that
generated body and nothing else. This tool establishes it the only way that cannot be faked by a
caller: it builds the body here, hashes the bytes, and writes the hash with its provenance to
``assets/calibration/synthetic-references.json``. A body is registered only when the operator's
``assets/calibration/policy.json`` declares it adult; the tool never declares anything itself.

``--check`` rebuilds and compares without writing: a generator change that alters the bytes fails
it, and the old hash then covers nothing, because no rebuilt file has it. Re-run without
``--check`` after an intended generator change, and review the diff of the registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy.reference import reference_sizes  # noqa: E402
from wardrobe.anatomy.vrm import build_reference_vrm  # noqa: E402
from wardrobe.body_surface.eligibility import SYNTHETIC_FILE, SYNTHETIC_SCHEMA  # noqa: E402

CALIBRATION = ROOT / "assets" / "calibration"
TEMPLATE = "MakeHuman hm08 female young adult (CC0), calibrated to ANSUR II women aged 21 and over"


def build_record(body_id: str) -> tuple[str, dict]:
    data = build_reference_vrm(body_id)
    return hashlib.sha256(data).hexdigest(), {
        "bodyId": body_id,
        "generator": "wardrobe.anatomy.vrm.build_reference_vrm",
        "template": TEMPLATE,
        "sizes": f"assets/anatomy/reference-sizes.json#{body_id}",
        "bytes": len(data),
        "declaredAdultBy": "assets/calibration/policy.json",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bodies", nargs="*", default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    policy = json.loads((CALIBRATION / "policy.json").read_text(encoding="utf-8"))["bodies"]
    known = set(reference_sizes()["sizes"])
    bodies = args.bodies or sorted(b for b in known if b in policy)
    for body in bodies:
        if body not in known:
            parser.error(f"{body} is not a reference body")
        if (policy.get(body) or {}).get("depictsAdult") is not True:
            parser.error(f"{body} is not declared adult in assets/calibration/policy.json")
    path = CALIBRATION / SYNTHETIC_FILE
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        current = {"schema": SYNTHETIC_SCHEMA, "references": {}}
    refs = dict(current.get("references") or {})
    failures = []
    for body in bodies:
        sha, record = build_record(body)
        registered = {s for s, r in refs.items() if r.get("bodyId") == body}
        print(f"{body}: {sha}{' (registered)' if sha in registered else ''}", flush=True)
        if args.check:
            if sha not in registered:
                failures.append(body)
            continue
        for stale in registered - {sha}:
            del refs[stale]
        refs[sha] = record
    if args.check:
        if failures:
            print("not reproduced (generator changed?):", ", ".join(failures))
        return 1 if failures else 0
    path.write_text(json.dumps({
        "schema": SYNTHETIC_SCHEMA,
        "about": "BE1. Forge's own generated adult reference bodies, keyed by the SHA-256 of the bytes "
                 "tools/anatomy/register_synthetic_references.py rebuilt. A record is a design clearance "
                 "for that exact file only: it says the body was generated here from a declared adult "
                 "template, so there is no character design to review. It is not a person's review and "
                 "is never reported as one. Library characters are never listed here.",
        "references": dict(sorted(refs.items(), key=lambda kv: kv[1]["bodyId"])),
    }, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
