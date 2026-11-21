#!/usr/bin/env sh
# Publish this repository to a Hugging Face Docker Space.
#
#     HF_TOKEN=hf_... sh deploy/huggingface/deploy.sh                 # ruslanmv/3D-Wardrobe-Forge
#     HF_TOKEN=hf_... HF_SPACE_REPO=you/your-space sh deploy/huggingface/deploy.sh
#     DRY_RUN=1 sh deploy/huggingface/deploy.sh                       # stage only, print the tree
#     HIDDEN_SOURCE=1 HF_TOKEN=hf_... sh deploy/huggingface/deploy.sh  # HS1: no code in the Space
#
# HS1. With HIDDEN_SOURCE=1 the Space gets no code: the staged source (with the Studio's React
# build made here) goes to the private dataset the Space already reads, on its own branch
# `forge-source`, and the Space gets deploy/huggingface/thin (Dockerfile, start.sh, source.env),
# its README and a requirements.txt of third-party names. start.sh downloads the code at start
# with the Space's existing HF_TOKEN. No Space variable or secret is added or changed.
# Without HIDDEN_SOURCE nothing in this script changes.
#
# What the Space receives is the committed HEAD, not the working tree: `git
# archive` of exactly what the Dockerfile copies. Uploading `.` (as this script
# used to) sent tests, docs, __pycache__, a local node_modules link and whatever
# was uncommitted at the time, so the Space could run code that is in no commit.
# The Space commit names the source commit instead.
#
# The avatar library is not uploaded: it is not in git, and the image fetches and
# sha256-verifies it at build time (a Space refuses plain-git files over 10 MB).
#
# The upload mirrors: files the stage no longer has are deleted from the Space
# (huggingface_hub never deletes .gitattributes), so a renamed module does not
# linger there.
set -eu

HF_SPACE_REPO="${HF_SPACE_REPO:-ruslanmv/3D-Wardrobe-Forge}"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

# Everything the Dockerfile COPYs, plus the licence the Space card declares.
PATHS="Dockerfile pyproject.toml LICENSE apps wardrobe worker tools assets"

# shellcheck disable=SC2086
if [ -n "$(git status --porcelain -- $PATHS deploy/huggingface)" ]; then
    echo "note: uncommitted changes under the deployed paths are NOT deployed; HEAD is." >&2
fi

SHA="$(git rev-parse --short HEAD)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# shellcheck disable=SC2086
git archive --format=tar HEAD $PATHS | tar -x -C "$STAGE"
# A Space reads its configuration (sdk: docker, app_port: 8080) from the front
# matter of its root README.md. The repository README has none, so the Space's
# own README goes in its place; the Dockerfile still finds a README.md for pip.
cp deploy/huggingface/SPACE_README.md "$STAGE/README.md"

echo "Staged $(find "$STAGE" -type f | wc -l | tr -d ' ') files from $SHA ($(du -sh "$STAGE" | cut -f1)) for $HF_SPACE_REPO"
if [ -n "${STAGE_TO:-}" ]; then
    # Keep a copy, e.g. to `docker build` exactly what the Space will build.
    rm -rf "$STAGE_TO" && cp -R "$STAGE" "$STAGE_TO"
fi

if [ "${HIDDEN_SOURCE:-0}" = "1" ]; then
    # The private dataset the Space already reads with its own HF_TOKEN: the code goes on a branch.
    HF_SOURCE_REPO="${HF_SOURCE_REPO:-${WARDROBE_HF_DATASET:-ruslanmv/3d-wardrobe-garments}}"
    # The Studio's React build (the main Dockerfile's `studio` stage), made here into the source.
    if [ "${SKIP_STUDIO:-0}" != "1" ]; then
        (cd "$STAGE/apps/studio/web" && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null \
            && rm -rf node_modules)
    fi
    THIN="$(mktemp -d)"
    trap 'rm -rf "$STAGE" "$THIN"' EXIT
    cp deploy/huggingface/thin/Dockerfile deploy/huggingface/thin/start.sh "$THIN/"
    cp deploy/huggingface/SPACE_README.md "$THIN/README.md"
    # Third-party names and versions only, exactly what `pip install ".[preview,s3,redis,hf]"` asks.
    python3 deploy/huggingface/thin/requirements.py "$STAGE/pyproject.toml" > "$THIN/requirements.txt"
    # Which code to run (publish.py pins the exact commit; a dry run names the branch).
    printf 'SRC_BRANCH=forge-source\nSRC_REVISION=\n' > "$THIN/source.env"
    echo "Hidden source: code -> $HF_SOURCE_REPO branch forge-source (private); Space -> $(ls "$THIN" | tr '\n' ' ')"
    if [ -n "${STAGE_TO:-}" ]; then rm -rf "$STAGE_TO" && cp -R "$STAGE" "$STAGE_TO"; fi
    if [ -n "${THIN_TO:-}" ]; then rm -rf "$THIN_TO" && cp -R "$THIN" "$THIN_TO"; fi
    if [ "${DRY_RUN:-0}" = "1" ]; then exit 0; fi
    : "${HF_TOKEN:?Set HF_TOKEN to a Hugging Face token with write access to $HF_SPACE_REPO and $HF_SOURCE_REPO}"
    export HF_TOKEN
    python3 deploy/huggingface/thin/publish.py "$HF_SPACE_REPO" "$HF_SOURCE_REPO" "$STAGE" "$THIN" "$SHA" \
        "$(git rev-parse HEAD)"
    exit 0
fi
if [ "${DRY_RUN:-0}" = "1" ]; then
    (cd "$STAGE" && find . -maxdepth 1 | sort)
    exit 0
fi

: "${HF_TOKEN:?Set HF_TOKEN to a Hugging Face token with write access to $HF_SPACE_REPO}"
export HF_TOKEN

hf upload "$HF_SPACE_REPO" "$STAGE" . --repo-type=space --delete='*' \
    --commit-message="Deploy $SHA" \
    --commit-description="From 3D-Wardrobe-Forge $(git rev-parse HEAD)"

# The Space's own settings: the profile, and the public URL assets are served
# under, read from the Space's domain rather than guessed from its name. Plain
# variables only; an API key, if you want one, is a secret you set yourself
# (see README.md in this folder).
python3 - "$HF_SPACE_REPO" <<'EOF'
import sys

from huggingface_hub import HfApi

repo = sys.argv[1]
api = HfApi()
domains = api.get_space_runtime(repo).raw.get("domains") or []
# F1. A queue cap is global, so it is right behind any number of proxies. The
# per-visitor limit needs WARDROBE_FORWARDED_HOPS to match the proxies in front of
# the Space, which this script cannot see: set both yourself once you have checked.
variables = {"WARDROBE_PROFILE": "space", "WARDROBE_JOB_CONCURRENCY": "1", "WARDROBE_QUEUE_CAP": "8"}
if domains:
    variables["PUBLIC_BASE_URL"] = f"https://{domains[0]['domain']}"
for key, value in variables.items():
    api.add_space_variable(repo, key, value)
    print(f"  {key}={value}")
print(f"Building: https://huggingface.co/spaces/{repo}?logs=build")
EOF
