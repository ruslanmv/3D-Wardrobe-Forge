"""HS1. Publish with the source hidden: the code to a PRIVATE repository, the thin loader to the Space.

    python3 deploy/huggingface/thin/publish.py <space> <source> <stage> <thin> <sha> <full sha>

The source repository is created private if missing and refused if it is not private. The Space
gets the thin folder only (its other files deleted), and the variables start.sh reads: SRC_REPO
and SRC_REVISION (the exact commit just uploaded, so every start runs this deploy). SRC_TOKEN,
the read-only token, is a Space SECRET: stored from HF_SOURCE_READ_TOKEN when given, otherwise
otherwise the deploy's own token. No token is ever printed.
"""

import os
import sys

from huggingface_hub import HfApi

space, source, stage, thin, sha, full = sys.argv[1:7]
api = HfApi()
api.create_repo(source, repo_type="model", private=True, exist_ok=True)
if not api.model_info(source).private:
    sys.exit(f"refusing: {source} is not private")
commit = api.upload_folder(
    repo_id=source, repo_type="model", folder_path=stage, delete_patterns="*",
    commit_message=f"Deploy {sha}", commit_description=f"From 3D-Wardrobe-Forge {full}",
)
api.upload_folder(repo_id=space, repo_type="space", folder_path=thin, delete_patterns="*",
                  commit_message=f"Deploy {sha} (source hidden)")
variables = {"WARDROBE_PROFILE": "space", "WARDROBE_JOB_CONCURRENCY": "1", "WARDROBE_QUEUE_CAP": "8",
             "SRC_REPO": source, "SRC_REVISION": commit.oid}
domains = api.get_space_runtime(space).raw.get("domains") or []
if domains:
    variables["PUBLIC_BASE_URL"] = f"https://{domains[0]['domain']}"
for key, value in variables.items():
    api.add_space_variable(space, key, value)
    print(f"  {key}={value}")
# One click: the Space must be able to read the source. A read-only token (HF_SOURCE_READ_TOKEN)
# when the owner gave one; otherwise the deploy's own token, which just wrote the source, so it
# certainly reads it (the Space's HF_TOKEN may be scoped to the dataset only). Stored as a Space
# SECRET, never shown to visitors, never printed.
read = os.environ.get("HF_SOURCE_READ_TOKEN", "").strip() or os.environ.get("HF_TOKEN", "").strip()
api.add_space_secret(space, "SRC_TOKEN", read)
given = "" if os.environ.get("HF_SOURCE_READ_TOKEN") else " from the deploy token"
print(f"  SRC_TOKEN set (secret){given}")
# HS1. Every earlier Space commit holds the full source (the old deploys): squash the Space's
# history to this one commit, so its Files tab and history show the loader only.
api.super_squash_history(repo_id=space, repo_type="space", commit_message=f"Deploy {sha} (source hidden)")
print("  Space history squashed: earlier commits with source are gone")
print(f"Building: https://huggingface.co/spaces/{space}?logs=build")
