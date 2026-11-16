#!/usr/bin/env python3
"""RU4. Find, and with --delete remove, look folders in the dataset that nothing can serve.

A look is served only through a prebuilt entry (``prebuilt/<key>.json``) or a wardrobe list
(``prebuilt/wardrobes/<id>.json``). Before RU4 the upload sent every ``looks/<id>/`` folder in
the storage root, so looks made with body art, in layers or from a free prompt went up with
nothing pointing at them. This reads every entry and list (the small JSON files only), lists
the folders no one names, and prints them; ``--delete`` removes them in one commit.

    python tools/dataset_orphans.py --repo ruslanmv/3d-wardrobe-garments            # dry run
    python tools/dataset_orphans.py --repo ruslanmv/3d-wardrobe-garments --delete
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wardrobe.storage.dataset_publish import look_of_entry, orphans  # noqa: E402


def main(argv=None) -> int:
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=raw)
    parser.add_argument("--repo", default=os.environ.get("WARDROBE_HF_DATASET", ""))
    parser.add_argument("--delete", action="store_true", help="Remove the orphans (one commit)")
    parser.add_argument("--report", type=Path, help="Write the orphan list here as JSON")
    opts = parser.parse_args(argv)
    from huggingface_hub import CommitOperationDelete, HfApi, snapshot_download

    token = os.environ.get("HF_TOKEN")
    api = HfApi(token=token)
    files = api.list_repo_files(opts.repo, repo_type="dataset")
    with tempfile.TemporaryDirectory() as scratch:
        snapshot_download(opts.repo, repo_type="dataset", allow_patterns=["prebuilt/**"], local_dir=scratch,
                          token=token)
        root = Path(scratch)
        entry_looks = [look_of_entry(p.read_bytes()) for p in (root / "prebuilt").glob("*.json")]
        listed = []
        for path in (root / "prebuilt" / "wardrobes").glob("*.json"):
            listed += [item.get("lookId") for item in json.loads(path.read_text()).get("looks", [])]
    lost = orphans(files, [x for x in entry_looks if x], [x for x in listed if x])
    used = {x for x in entry_looks if x} | {x for x in listed if x}
    sizes = {}
    for info in api.list_repo_tree(opts.repo, repo_type="dataset", path_in_repo="looks", recursive=True):
        parts = getattr(info, "path", "").split("/")
        if len(parts) >= 3 and parts[1] in lost:
            sizes[parts[1]] = sizes.get(parts[1], 0) + (getattr(info, "size", 0) or 0)
    print(f"{len(used)} looks served, {len(lost)} orphan folders, {sum(sizes.values()) / 1e6:.1f} MB")
    if opts.report:
        opts.report.write_text(json.dumps({"orphans": lost, "bytes": sizes}, indent=1))
    if opts.delete and lost:
        api.create_commit(repo_id=opts.repo, repo_type="dataset",
                          operations=[CommitOperationDelete(path_in_repo=f"looks/{look}/") for look in lost],
                          commit_message=f"remove {len(lost)} looks no prebuilt entry or list names (RU4)")
        print(f"deleted {len(lost)} orphan folders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
