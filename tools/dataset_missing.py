#!/usr/bin/env python3
"""DS1. How many ready-made looks the dataset is missing, per character — read-only, no token.

Asks a running Forge (the Space by default) what each character's list already holds and what
the catalogue and outfit dictionary would make, exactly as ``tools/prebuild.py --missing-only``
plans it. Run it before a populate run (is it worth it?) and after (did it work?).

    .venv/bin/python tools/dataset_missing.py
    .venv/bin/python tools/dataset_missing.py --forge http://127.0.0.1:8090 --admin-token-file <file>

Without an admin token only the public catalogue is counted: adult-only garments are listed to an
admin session alone, so the true total can be a little higher than a guest's count.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--forge", default="https://ruslanmv-3d-wardrobe-forge.hf.space")
    parser.add_argument("--admin-token-file", help="Count adult-only garments too")
    parser.add_argument("--slugs", help="Comma-separated characters; default all")
    parser.add_argument("--colours", type=int, default=3)
    opts = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location("prebuild", ROOT / "tools/prebuild.py")
    pb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb)
    token = Path(opts.admin_token_file).expanduser().read_text().strip() if opts.admin_token_file else None
    forge = pb.Forge(opts.forge, token)
    slugs = opts.slugs.split(",") if opts.slugs else None
    pairs = pb.plan(forge, slugs, None, opts.colours) + pb.plan_outfits(forge, slugs, None)
    pb.mark_listed(forge, pairs)
    missing = [p for p in pairs if not p.get("listed") and not p.get("skip")]
    print(
        f"planned {len(pairs)} · listed {sum(bool(p.get('listed')) for p in pairs)} · "
        f"missing {len(missing)} · skipped by the adult gate {sum(bool(p.get('skip')) for p in pairs)}"
    )
    for slug, n in sorted(collections.Counter(p["slug"] for p in missing).items()):
        kinds = collections.Counter(
            "outfit" if p["templateId"].startswith("outfit:") else "garment"
            for p in missing
            if p["slug"] == slug
        )
        print(f"  {slug:<26} {n:>4} missing ({kinds['garment']} garments, {kinds['outfit']} outfits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
