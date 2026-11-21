#!/bin/bash
# HS1. Start Forge from code that is not in this image (see Dockerfile beside this file).
#
# Nothing new in the Space's settings (the owner's rule): the code is read from the private
# dataset the Space already uses (WARDROBE_HF_DATASET), on its own branch, with the Space's
# existing HF_TOKEN secret. Which commit of that branch to run is in /app/source.env, written by
# the deploy (a branch name and a commit hash, no code), so every start runs the deployed code.
#
#   SRC_DIR   for CI only: run code already on disk instead of downloading it
#
# The token is used once, to download, and never printed; nothing is written outside /app/src.
set -eu
cd /app
SRC_BRANCH=forge-source
SRC_REVISION=""
# shellcheck disable=SC1091
[ -f /app/source.env ] && . /app/source.env
if [ -n "${SRC_DIR:-}" ]; then
  echo "start: code from $SRC_DIR (local)"
  cp -R "$SRC_DIR"/. /app/src/
else
  : "${WARDROBE_HF_DATASET:?WARDROBE_HF_DATASET is not set (the Space's dataset variable)}"
  : "${HF_TOKEN:?HF_TOKEN is not set (the Space's secret for its dataset)}"
  export SRC_REVISION="${SRC_REVISION:-$SRC_BRANCH}"
  echo "start: downloading the code from ${WARDROBE_HF_DATASET}@${SRC_REVISION}"
  python - <<'EOF'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    os.environ["WARDROBE_HF_DATASET"],
    repo_type="dataset",
    revision=os.environ["SRC_REVISION"],
    token=os.environ["HF_TOKEN"],
    local_dir="/app/src",
)
EOF
fi
cd /app/src
# The code only: its dependencies are already in the image (requirements.txt).
pip install --no-cache-dir --no-deps --user . >/dev/null
if [ "${FETCH_LIBRARY:-1}" = "1" ]; then python tools/fetch_library.py; fi
exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
