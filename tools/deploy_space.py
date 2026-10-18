"""Deploy this checkout to the Hugging Face Space, as the Space has always been built.

    HF_TOKEN=... python tools/deploy_space.py [--space ruslanmv/3D-Wardrobe-Forge] [--dry-run]

The Space is a Docker Space built from a copy of one commit: the files its Dockerfile copies
(``SPACE_FILES``) and the Space's own README (``deploy/huggingface/README.md``, whose front
matter tells Hugging Face how to run it). Those are staged and uploaded as one commit named
after the source commit, ``Deploy <sha>``. Files the Space holds under the copied directories
that this checkout no longer has are deleted, so the Space never runs a stale module; the
Space's own ``.gitattributes`` is left as it is.

``.github/workflows/deploy-space.yml`` runs this on every push to ``main`` (with the
repository secret ``HF_TOKEN``), so the Space follows GitHub.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = "ruslanmv/3D-Wardrobe-Forge"
SPACE_README = ROOT / "deploy" / "huggingface" / "README.md"
#: What the Dockerfile copies (and the licence): nothing else is the Space's.
SPACE_FILES = ("Dockerfile", "LICENSE", "pyproject.toml")
SPACE_DIRS = ("apps", "assets", "tools", "wardrobe", "worker")


def tracked(directory: str) -> list[str]:
    """The files git tracks under ``directory``: never a local cache or an untracked render."""
    out = subprocess.run(["git", "ls-files", "-z", directory], cwd=ROOT, check=True, capture_output=True)
    return [name for name in out.stdout.decode().split("\0") if name]


def stage(into: Path) -> int:
    count = 0
    for name in SPACE_FILES:
        shutil.copy2(ROOT / name, into / name)
        count += 1
    for directory in SPACE_DIRS:
        for name in tracked(directory):
            target = into / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
            count += 1
    shutil.copy2(SPACE_README, into / "README.md")
    return count + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", default=SPACE)
    parser.add_argument("--dry-run", action="store_true", help="stage and list, upload nothing")
    args = parser.parse_args()
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)
        count = stage(staged)
        print(f"staged {count} files from {sha}")
        if args.dry_run:
            return 0
        token = os.environ.get("HF_TOKEN")
        if not token:
            print("HF_TOKEN is not set", file=sys.stderr)
            return 2
        from huggingface_hub import HfApi

        info = HfApi(token=token).upload_folder(
            repo_id=args.space, repo_type="space", folder_path=staged,
            commit_message=f"Deploy {sha}",
            delete_patterns=[f"{d}/**" for d in SPACE_DIRS],
        )
        print(f"deployed {sha} to https://huggingface.co/spaces/{args.space}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
