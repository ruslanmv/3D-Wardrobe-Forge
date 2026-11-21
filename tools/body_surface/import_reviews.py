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
    """Merge an export into ``root`` (``review_files.merge_export``, the one implementation)."""
    from wardrobe.body_surface.review_files import merge_export

    return merge_export(export, root)


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
