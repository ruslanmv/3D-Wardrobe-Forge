"""Fetch one checksum-pinned CC0 reference avatar for the catalog builder.

Reuses the audited library manifest and fetch routine, without downloading
the other four Studio models. No adult status is inferred from appearance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.fetch_library import LIBRARY_ROOT, fetch_one, matches  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", default="avatar-sample-a")
    args = parser.parse_args()
    data = json.loads((LIBRARY_ROOT / "models.json").read_text())
    entry = next((item for item in data["items"] if item["slug"] == args.avatar), None)
    if entry is None:
        parser.error(f"unknown pinned library avatar: {args.avatar}")
    if str(entry.get("license", "")).upper() not in {"CC0", "CC0-1.0"}:
        parser.error("catalog previews require a redistributable CC0 reference avatar")
    target = LIBRARY_ROOT / entry["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not matches(target, entry):
        print(f"Fetching checksum-pinned {args.avatar}: {entry['bytes']} bytes")
        fetch_one(entry, target, None)
    if not matches(target, entry):
        raise SystemExit("reference avatar checksum verification failed")
    print(f"Verified {target} ({entry['sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
