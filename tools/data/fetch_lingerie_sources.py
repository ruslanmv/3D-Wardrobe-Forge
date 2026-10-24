"""RL1. Fetch the lingerie reference files pinned in sources.lock.json, and check them.

    python tools/data/fetch_lingerie_sources.py              # fetch what is missing, verify all
    python tools/data/fetch_lingerie_sources.py --refresh    # fetch every file again, verify all
    python tools/data/fetch_lingerie_sources.py --record     # first fetch of a new entry: write its hash

Every file is fetched from a URL pinned to a commit, never from a branch, so the same bytes
come back next year. A file whose hash differs from the lock is refused, not kept: the lock
says what was inspected and licensed on its verification date, and something else arriving
under that URL is not it. ``--record`` is only for an entry whose ``sha256`` is still null —
it will not overwrite a hash already recorded.

Only sources the lock marks redistributable have files at all (a ``path`` in this
repository); research-only and GPL sources have none, so nothing here can download them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "assets" / "reference" / "lingerie" / "sources.lock.json"
#: Licences a file may be copied into this MIT repository under.
REDISTRIBUTABLE = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - pinned https URLs from the lock
        return response.read()


def run(refresh: bool, record: bool) -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    changed, failures = False, []
    for source in lock["sources"]:
        for entry in source.get("files", []):
            if source["license"] not in REDISTRIBUTABLE:
                failures.append(
                    f"{source['id']}: {source['license']} may not be copied here, yet it lists files"
                )
                continue
            target = ROOT / entry["path"]
            if target.is_file() and not refresh:
                data = target.read_bytes()
            else:
                data = fetch(entry["url"])
            digest = sha256(data)
            if entry["sha256"] is None:
                if not record:
                    failures.append(f"{entry['path']}: no hash recorded (inspect it, then run with --record)")
                    continue
                entry["sha256"], changed = digest, True
            elif digest != entry["sha256"]:
                failures.append(f"{entry['path']}: sha256 {digest} is not the recorded {entry['sha256']}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
            print(f"ok  {entry['path']}")
    if changed:
        LOCK.write_text(json.dumps(lock, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    formatter = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=formatter)
    parser.add_argument("--refresh", action="store_true", help="fetch every file again")
    parser.add_argument("--record", action="store_true", help="write the hash of entries that have none")
    args = parser.parse_args()
    return run(args.refresh, args.record)


if __name__ == "__main__":
    raise SystemExit(main())
