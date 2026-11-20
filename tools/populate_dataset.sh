#!/bin/bash
# DS1. Populate the Hugging Face dataset with every missing ready-made look, from one machine,
#      one character at a time, never overwriting what the dataset holds.
#
# Why this shape (learned on 2026-11-20, building ~530 looks from a cloud session):
#   * One character per Forge process: Forge is started fresh for each, so memory never piles up,
#     and the character's local files are deleted once they are published — a run over all eight
#     needs ~110 MB–2 GB of disk at a time instead of the ~12 GB the whole set weighs.
#   * --missing-only: a look a character's list already has is not even sent (not to the cache,
#     not to a job): nothing is rebuilt, nothing replaced. Forge, signed in as a throwaway admin,
#     sees the adult-only garments a guest does not.
#   * publish_prebuilt.py without --overwrite: every list is merged with the dataset's copy and
#     the dataset's entry wins (PB7); a run that made nothing makes no commit.
#   * A watchdog stops the run (cleanly: what is published stays) under MIN_DISK_GB free disk or
#     MIN_MEM_MB available memory, before the container is killed for space or memory.
#   * WARDROBE_STORAGE_BACKEND=hf reads what the dataset already has, so the plan is the real one.
#
# Needs: HF_TOKEN in the environment (a token with write access to the dataset; never put it in a
# file, a commit or a log), `.venv` with `pip install -e ".[hf]"`, and every library character on
# disk (`tools/fetch_library.py`). The prebuild workflow (Actions ▸ Prebuild wardrobe) does the
# same job on GitHub's runners in parallel; use this when a session cannot start workflows.
#
#   HF_TOKEN=… tools/populate_dataset.sh                       # every character
#   HF_TOKEN=… tools/populate_dataset.sh vroid-rinna fem-vroid # some
#   HF_TOKEN=… EXTRA="--only lingerie" tools/populate_dataset.sh
#   tools/dataset_missing.py                                   # before and after: what is missing
set -u
: "${HF_TOKEN:?set HF_TOKEN (write access to the dataset) in the environment}"
FORGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-${TMPDIR:-/tmp}/populate-dataset}"
PORT="${PORT:-8093}"
DATASET="${DATASET:-ruslanmv/3d-wardrobe-garments}"
MIN_DISK_GB="${MIN_DISK_GB:-3}"
MIN_MEM_MB="${MIN_MEM_MB:-1500}"
EXTRA="${EXTRA:-}"
mkdir -p "$WORK"; chmod 700 "$WORK"
cd "$FORGE_DIR"
if [ "$#" -gt 0 ]; then SLUGS="$*"; else
  SLUGS=$(.venv/bin/python -c "from wardrobe.config import get_settings; from wardrobe.library import AvatarLibrary
print(' '.join(a.slug for a in AvatarLibrary.from_directory(get_settings().wardrobe_library_root).available()))")
fi
export HF_TOKEN WARDROBE_STORAGE_BACKEND=hf WARDROBE_HF_DATASET="$DATASET"

stop_all() { pkill -f "uvicorn apps.api.main:app --port $PORT"; pkill -f "tools/prebuild.py --forge http://127.0.0.1:$PORT"; }

watchdog() {
  while sleep 30; do
    disk=$(df -Pk "$WORK" | tail -1 | awk '{print $4}'); mem=$(free -m | awk '/Mem:/{print $7}')
    if [ "$disk" -lt $((MIN_DISK_GB * 1024 * 1024)) ] || [ "$mem" -lt "$MIN_MEM_MB" ]; then
      echo "=== WATCHDOG STOP $(date -u +%H:%M): ${disk} KB disk, ${mem} MB memory"; touch "$WORK/.stop"; stop_all; return
    fi
  done
}
rm -f "$WORK/.stop"; watchdog & WATCH=$!; trap 'kill $WATCH 2>/dev/null; stop_all' EXIT

for slug in $SLUGS; do
  [ -f "$WORK/.stop" ] && break
  echo "=== $slug start $(date -u +%H:%M)"
  export WARDROBE_STORAGE_ROOT="$WORK/root-$slug"
  # A throwaway admin password, for this Forge only: never printed, gone when the loop moves on.
  PASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
  WARDROBE_ADMIN_PASSWORD="$PASS" .venv/bin/python -m uvicorn apps.api.main:app --port "$PORT" \
    > "$WORK/forge-$slug.log" 2>&1 &
  FORGE=$!
  for i in $(seq 1 120); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 1; done
  curl -s -X POST "http://127.0.0.1:$PORT/v1/admin/session" -H 'content-type: application/json' \
    -d "{\"password\":\"$PASS\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' > "$WORK/.admin"
  chmod 600 "$WORK/.admin"; PASS=""
  # shellcheck disable=SC2086
  .venv/bin/python tools/prebuild.py --forge "http://127.0.0.1:$PORT" --admin-token-file "$WORK/.admin" \
    --slugs "$slug" --outfits --missing-only --workers 1 --job-timeout 900 --report "$WORK/report-$slug.json" $EXTRA
  kill "$FORGE" 2>/dev/null; wait "$FORGE" 2>/dev/null; rm -f "$WORK/.admin"
  if [ -d "$WARDROBE_STORAGE_ROOT/prebuilt" ]; then
    .venv/bin/python tools/publish_prebuilt.py --root "$WARDROBE_STORAGE_ROOT" --message "prebuild: $slug (missing only)"
    echo "publish exit $?"
  fi
  rm -rf "$WARDROBE_STORAGE_ROOT"
  echo "=== $slug done $(date -u +%H:%M) · disk free $(df -h "$WORK" | tail -1 | awk '{print $4}')"
done
echo "=== ALL DONE $(date -u +%H:%M) · reports in $WORK/report-*.json"
