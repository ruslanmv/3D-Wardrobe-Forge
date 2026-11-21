#!/usr/bin/env python3
"""PV2. How many private bare looks each character still misses — read-only.

The private half of ``tools/dataset_missing.py`` (which counts garments and outfits): what
``tools/populate_private.sh`` would still make, per character, against what a Forge lists to a
read grant. The plan is ``tools/prebuild_private.py``'s own (every pack group, the extras sets,
After Dark · Bare's named looks, at ``--presets``), and the repaint is its BD25 rule (detailed
looks opening her anus, built before ``--repaint-before``), so the numbers are what a run does.
Use it before a population run (how long?) and after a stop (what is left?).

    FORGE_GRANT=… .venv/bin/python tools/dataset_private_missing.py
    FORGE_GRANT=… .venv/bin/python tools/dataset_private_missing.py --forge http://127.0.0.1:8096 \
        --slugs avatar-sample-a

The grant is read from FORGE_GRANT in the environment only, sent in its header, never printed.
Private lists are not shown to a guest, so without a grant this tool refuses to guess.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--forge", default="https://ruslanmv-3d-wardrobe-forge.hf.space")
    parser.add_argument("--slugs", help="Comma-separated characters; default all available")
    parser.add_argument("--presets", default="natural")
    parser.add_argument(
        "--repaint-before", default="2026-11-21T10:30", help="BD29's fix; as populate_private.sh"
    )
    parser.add_argument("--repaint-skip", default="vroid-rinna", help="As populate_private.sh REPAINT_SKIP")
    parser.add_argument("--skip-groups", default="rough-strong", help="As SKIP_GROUPS (BD37)")
    opts = parser.parse_args(argv)
    grant = os.environ.get("FORGE_GRANT", "").strip()
    if not grant:
        print(
            "set FORGE_GRANT (a read grant) in the environment: private lists are not shown to a guest",
            file=sys.stderr,
        )
        return 2

    spec = importlib.util.spec_from_file_location("prebuild_private", ROOT / "tools/prebuild_private.py")
    pp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pp)

    def get(path: str) -> dict:
        request = urllib.request.Request(
            opts.forge.rstrip("/") + path, headers={"Accept": "application/json", "X-Wardrobe-Grant": grant}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)

    skip_groups = {g for g in opts.skip_groups.split(",") if g}
    packs = pp.skip_packs(pp.state_groups(pp.load_names(pp.STATES_PATH, "states")), skip_groups)
    avatars = [a for a in get("/v1/library").get("avatars", []) if a.get("available")]
    if opts.slugs:
        avatars = [a for a in avatars if a["slug"] in opts.slugs.split(",")]
    presets = [p.strip() for p in opts.presets.split(",") if p.strip()]
    pairs = pp.plan(avatars, presets, packs, pp.EXTRAS_SETS, pp.bare_looks())
    opened = pp.anus_open_of()
    skip = set(filter(None, opts.repaint_skip.split(",")))
    total = collections.Counter()
    print(f"{'character':<24} {'packs':>5} {'extras':>6} {'named':>5} {'repaint':>7} {'to build':>8}")
    for avatar in avatars:
        slug = avatar["slug"]
        looks = get(f"/v1/library/{slug}/prebuilt").get("looks", [])
        held = {
            pp.identity(b.get("detail"), b.get("states"), b.get("extras"))
            for b in (look.get("body") for look in looks)
            if isinstance(b, dict)
        }
        row = collections.Counter()
        for pair in pairs:
            if pair["slug"] != slug or pair.get("skip"):
                continue
            if pp.identity(pair["preset"], pair["states"], pair["extras"]) in held:
                continue
            kind = (
                "named"
                if pair["look"].startswith("ad:")
                else "extras"
                if pair["look"].startswith("core+")
                else "packs"
            )
            row[kind] += 1
        row["repaint"] = (
            0 if slug in skip else len(pp.repaint_plan(looks, slug, opts.repaint_before, 0.5, opened))
        )
        row["to build"] = sum(row.values())
        total.update(row)
        cells = f"{row['packs']:>5} {row['extras']:>6} {row['named']:>5} {row['repaint']:>7}"
        print(f"{slug:<24} {cells} {row['to build']:>8}")
    print(
        f"{'total':<24} {total['packs']:>5} {total['extras']:>6} {total['named']:>5} {total['repaint']:>7} "
        f"{total['to build']:>8}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
