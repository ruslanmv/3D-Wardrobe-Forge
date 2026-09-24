#!/usr/bin/env python3
"""Fetch the Studio's avatar library and prove every byte of it.

The library is the five CC0 VRoid sample avatars that yourfriend.online ships in
``public/avatar/models/cc0/``. ``assets/library/models.json`` is a verbatim copy
of that repository's provenance manifest, and it pins each file by size and
SHA-256. The binaries themselves are not committed here: five files of 11-15 MB
would put 67 MB into this repository's history for good, and a Hugging Face
Space refuses any plain-git file over 10 MB. Fetching against pinned hashes gives
identical bytes with none of that.

Sources are tried in order, and the hash decides — not the source:

1. ``--from DIR``, a local checkout (development, offline builds);
2. yourfriend itself, the repository these avatars are vendored from;
3. the upstream ``source`` URL recorded in the manifest.

A file that is already present and already matches is left alone, so a second
run costs one hash per file. A download that does not match is discarded, never
written over a good file. Stdlib only, because the Dockerfile runs this before
``pip install``.

    python tools/fetch_library.py                 # fetch what is missing
    python tools/fetch_library.py --check-only    # verify, download nothing
    python tools/fetch_library.py --from ../yourfriend/public/avatar/models/cc0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_ROOT = REPO_ROOT / "assets" / "library"
# HEAD, not a branch name: yourfriend's default branch is `master`, and a rename
# should not break the build. The hash below is the pin, not the ref.
YOURFRIEND_RAW = "https://raw.githubusercontent.com/ruslanmv/yourfriend/HEAD/public/avatar/models/cc0/{file}"
TIMEOUT_S = 120


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches(path: Path, item: dict) -> bool:
    return path.is_file() and path.stat().st_size == item["bytes"] and sha256_of(path) == item["sha256"]


def candidates(item: dict, local: Path | None) -> list[str]:
    found = []
    if local is not None:
        # resolve(): as_uri() refuses a relative path, and `--from ../yourfriend/...` is the usual one.
        found.append((local.resolve() / item["file"]).as_uri())
    found.append(YOURFRIEND_RAW.format(file=item["file"]))
    if item.get("source"):
        found.append(item["source"])
    return found


def fetch_one(item: dict, target: Path, local: Path | None) -> str:
    """Put a verified copy at ``target``; return where it came from."""
    for url in candidates(item, local):
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".part") as tmp:
            staging = Path(tmp.name)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response, staging.open("wb") as out:
                shutil.copyfileobj(response, out)
            if matches(staging, item):
                # NamedTemporaryFile creates 0600. Left that way, a server running as
                # any other user than the one who fetched cannot read the avatar.
                staging.chmod(0o644)
                staging.replace(target)
                return url
            print(f"  ! {item['file']}: {url} did not match the pinned hash, discarded", file=sys.stderr)
        except OSError as exc:
            print(f"  ! {item['file']}: {url} unavailable ({exc})", file=sys.stderr)
        finally:
            staging.unlink(missing_ok=True)
    raise RuntimeError(f"{item['file']}: no source produced the pinned bytes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=LIBRARY_ROOT)
    parser.add_argument("--from", dest="local", type=Path, default=None, help="copy from a local checkout")
    parser.add_argument("--check-only", action="store_true", help="verify, download nothing")
    args = parser.parse_args(argv)

    manifest = json.loads((args.root / "models.json").read_text(encoding="utf-8"))
    failures = 0
    for item in manifest["items"]:
        target = args.root / item["file"]
        if matches(target, item):
            print(f"  ok  {item['file']}")
            continue
        if args.check_only:
            print(f"  --  {item['file']}: missing or does not match its pinned hash")
            failures += 1
            continue
        try:
            source = fetch_one(item, target, args.local)
            print(f"  +   {item['file']}  <- {source}")
        except RuntimeError as exc:
            print(f"  xx  {exc}", file=sys.stderr)
            failures += 1

    total = len(manifest["items"])
    print(f"{total - failures}/{total} library avatars verified in {args.root}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
