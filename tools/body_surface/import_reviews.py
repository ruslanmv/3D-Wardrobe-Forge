#!/usr/bin/env python3
"""RX1. Commit the reviews recorded in a Space's Studio: an export, merged into this repository.

The Studio records each person's finding (``adult-design-reviews.json``) and detail review
(``adult-detail-reviews.json``, with its review packet) on the disk Forge runs on. On the Space
that disk is lost at a restart, and the Prebuild workflow and a local Forge never see it, so a
character cleared in the Studio still had every detailed look refused elsewhere. The Review page's
**Export reviews** button downloads them all as one file; this merges that file into
``assets/body_surface/`` so that it can be committed, under the reviewer's name:

    .venv/bin/python tools/body_surface/import_reviews.py forge-reviews-2026-11-20.json
    git add assets/body_surface && git commit

Nothing is made here, only copied, and a review is never replaced: a finding is write-once for its
bytes, so an entry this repository already has for a SHA-256 is kept as it is, and a different one
in the export is reported, not written. A detail review is taken only as Forge's own rules allow
it to be recorded: its packet is in the export and is for those bytes, its evidence has at least
``DETAIL_EVIDENCE_CHARS`` characters, the reviewer said they examined it, and the same bytes have a
``clearly-adult`` design finding (here or in the export). Anything else is refused with its reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DESIGN_FILE = "adult-design-reviews.json"


def load(path: Path, schema: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": schema, "reviews": {}}


def merge(export: dict, root: Path) -> dict:
    """Merge an export into ``root``; returns what was added, kept and refused, with reasons."""
    from wardrobe.body_surface.eligibility import (
        DETAIL_EVIDENCE_CHARS,
        DETAIL_REVIEWS_FILE,
        DETAIL_REVIEWS_SCHEMA,
    )

    if export.get("schema") != "wardrobe.reviews.export.v1":
        raise ValueError("not a Forge review export (schema wardrobe.reviews.export.v1)")
    out = {"design": [], "detail": [], "kept": [], "refused": []}
    design_path, detail_path = root / DESIGN_FILE, root / DETAIL_REVIEWS_FILE
    here_design = load(design_path, (export.get("designReviews") or {}).get("schema", ""))
    here_detail = load(detail_path, DETAIL_REVIEWS_SCHEMA)
    packets = export.get("packets") or {}

    for sha, entry in ((export.get("designReviews") or {}).get("reviews") or {}).items():
        mine = here_design.setdefault("reviews", {})
        if sha in mine:
            out["kept" if mine[sha] == entry else "refused"].append(
                sha if mine[sha] == entry else f"{sha[:12]} design: a different finding is already here")
            continue
        mine[sha] = entry
        out["design"].append(sha)

    for sha, entry in ((export.get("detailReviews") or {}).get("reviews") or {}).items():
        mine = here_detail.setdefault("reviews", {})
        if sha in mine:
            out["kept"].append(sha)
            continue
        design = (here_design.get("reviews") or {}).get(sha) or {}
        packet = packets.get(sha)
        why = None
        if design.get("outcome") != "clearly-adult":
            why = "no clearly-adult design finding for these bytes"
        elif not packet or (packet.get("file") or {}).get("sha256") != sha:
            why = "its review packet is missing or for other bytes"
        elif len(str(entry.get("evidence", "")).strip()) < DETAIL_EVIDENCE_CHARS:
            why = f"fewer than {DETAIL_EVIDENCE_CHARS} characters of evidence"
        elif not entry.get("examined") or not str(entry.get("reviewer", "")).strip():
            why = "no reviewer, or not marked as examined"
        if why:
            out["refused"].append(f"{sha[:12]} detail: {why}")
            continue
        packet_path = root / "packets" / f"{sha}.json"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        if not packet_path.exists():
            packet_path.write_text(json.dumps(packet, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        # The Space wrote its own absolute path; here the packet is the committed file.
        mine[sha] = {**entry, "packet": f"packets/{sha}.json"}
        out["detail"].append(sha)

    for path, content in ((design_path, here_design), (detail_path, here_detail)):
        path.write_text(json.dumps(content, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("export", type=Path, help="The file the Review page's Export reviews downloaded")
    parser.add_argument("--root", type=Path, default=ROOT / "assets" / "body_surface")
    opts = parser.parse_args(argv)
    result = merge(json.loads(opts.export.read_text(encoding="utf-8")), opts.root)
    print(f"design findings added {len(result['design'])}, detail reviews added {len(result['detail'])}, "
          f"already here {len(result['kept'])}, refused {len(result['refused'])}")
    for line in result["refused"]:
        print(f"  refused {line}")
    return 1 if result["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
