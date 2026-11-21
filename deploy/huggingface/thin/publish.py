"""HS1. Publish with the source hidden, changing nothing in the Space's settings.

    python3 deploy/huggingface/thin/publish.py <space> <dataset> <stage> <thin> <sha> <full sha>

The owner's rule: one click, no new repository, secret or variable, none changed. So the code
goes to the private dataset the Space already reads (its WARDROBE_HF_DATASET, with its existing
HF_TOKEN secret), on its own branch `forge-source`, never on the branch that holds the looks.
The Space gets the thin folder only (its other files deleted) plus source.env, naming the exact
commit of that branch to run. Its history is squashed, so the old deploys' code is gone too.
Refused if the dataset is not private. No token is ever printed.
"""

import sys
from pathlib import Path

from huggingface_hub import HfApi

BRANCH = "forge-source"
space, dataset, stage, thin, sha, full = sys.argv[1:7]
api = HfApi()
if not api.dataset_info(dataset).private:
    sys.exit(f"refusing: {dataset} is not private, the code would be public")
api.create_branch(dataset, repo_type="dataset", branch=BRANCH, exist_ok=True)
api.upload_folder(
    repo_id=dataset, repo_type="dataset", revision=BRANCH, folder_path=stage, delete_patterns="*",
    commit_message=f"Forge source {sha}", commit_description=f"From 3D-Wardrobe-Forge {full}",
)
# The code branch keeps one commit (the dataset's main branch, the looks, is never touched).
api.super_squash_history(repo_id=dataset, repo_type="dataset", branch=BRANCH,
                         commit_message=f"Forge source {sha}")
refs = api.list_repo_refs(dataset, repo_type="dataset").branches
revision = next(b.target_commit for b in refs if b.name == BRANCH)
Path(thin, "source.env").write_text(f"SRC_BRANCH={BRANCH}\nSRC_REVISION={revision}\n")
api.upload_folder(repo_id=space, repo_type="space", folder_path=thin, delete_patterns="*",
                  commit_message=f"Deploy {sha} (source hidden)")
# Every earlier Space commit holds the full source (the old deploys): one commit, the loader only.
api.super_squash_history(repo_id=space, repo_type="space", commit_message=f"Deploy {sha} (source hidden)")
print(f"  code: {dataset} branch {BRANCH} @ {revision[:12]} (private)")
print("  Space: loader only, history squashed; its variables and secrets untouched")
print(f"Building: https://huggingface.co/spaces/{space}?logs=build")
