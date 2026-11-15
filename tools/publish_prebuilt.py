#!/usr/bin/env python3
"""RU4. Publish a storage root's prebuilt looks to the dataset: what CI's upload step runs.

Only looks a prebuilt entry names go up (a look nothing points at is never served), with the
entries and every wardrobe list merged with the dataset's copy (PB7, RU1's identity). One commit.

    python tools/publish_prebuilt.py --root .prebuilt --repo ruslanmv/3d-wardrobe-garments
    python tools/publish_prebuilt.py ... --overwrite   # this run's builds replace listed ones
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wardrobe.storage.dataset_publish import hub_download, publish  # noqa: E402


def main(argv=None) -> int:
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=raw)
    root = os.environ.get("WARDROBE_STORAGE_ROOT", ".wardrobe")
    parser.add_argument("--root", type=Path, default=Path(root))
    parser.add_argument("--repo", default=os.environ.get("WARDROBE_HF_DATASET", ""))
    parser.add_argument("--overwrite", action="store_true", help="This run's looks replace the listed ones")
    parser.add_argument("--message", default="publish prebuilt looks")
    # BI4. Private looks go up only to a dataset the hub reports private, unless this says so.
    parser.add_argument("--include-private", action="store_true", default=None,
                        help="Also publish private looks (only for a dataset you know is private)")
    opts = parser.parse_args(argv)
    if not opts.repo:
        print("no dataset: pass --repo or set WARDROBE_HF_DATASET", file=sys.stderr)
        return 2
    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    result = publish(HfApi(token=token), opts.repo, opts.root, keep_existing=not opts.overwrite,
                     message=opts.message, download=hub_download(token),
                     include_private=opts.include_private)
    for key in result["heldBack"]:
        print(f"::warning::{key}: the dataset copy could not be read; not uploaded this time")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
