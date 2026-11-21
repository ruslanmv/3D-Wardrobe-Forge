#!/bin/bash
# HS1. Start Forge from code that is not in this image (see Dockerfile beside this file).
#
#   SRC_REPO      the private repository holding the code (a Space variable, set by deploy.sh)
#   SRC_REVISION  the exact commit to run (a Space variable: every start runs the deployed code)
#   SRC_TOKEN     a read-only token for SRC_REPO (a Space SECRET, never a variable or a file);
#                 without it, the Space's own HF_TOKEN secret (it already reads and writes the
#                 dataset), so a one-click deploy needs no new secret
#   SRC_DIR       for CI only: run code already on disk instead of downloading it
#
# The token is used once, to download, and never printed; nothing is written outside /app/src.
set -eu
cd /app
if [ -n "${SRC_DIR:-}" ]; then
  echo "start: code from $SRC_DIR (local)"
  cp -R "$SRC_DIR"/. /app/src/
else
  : "${SRC_REPO:?SRC_REPO is not set (a Space variable)}"
  SRC_TOKEN="${SRC_TOKEN:-${HF_TOKEN:-}}"
  : "${SRC_TOKEN:?neither SRC_TOKEN nor HF_TOKEN is set (a Space secret with read access to SRC_REPO)}"
  export SRC_TOKEN
  echo "start: downloading ${SRC_REPO}@${SRC_REVISION:-main}"
  python - <<'EOF'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    os.environ["SRC_REPO"],
    revision=os.environ.get("SRC_REVISION") or None,
    token=os.environ["SRC_TOKEN"],
    local_dir="/app/src",
)
EOF
fi
cd /app/src
# The code only: its dependencies are already in the image (requirements.txt).
pip install --no-cache-dir --no-deps --user . >/dev/null
if [ "${FETCH_LIBRARY:-1}" = "1" ]; then python tools/fetch_library.py; fi
exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
