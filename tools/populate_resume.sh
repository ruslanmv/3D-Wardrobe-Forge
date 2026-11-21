#!/bin/bash
# PV2. The full population run (tools/populate_private.sh), made to survive: a character that
# fails, a run stopped by the watchdog, this container replaced, the session that started it gone.
#
# Why this shape (2026-11-21, before a run of ~690 looks over several days):
#   * The dataset is the only state that matters. Everything populate_private.sh does is
#     missing-only (a listed look is never sent again), and its repaint picks only looks built
#     before REPAINT_BEFORE, which a repainted look no longer is. So "resume" is simply "run it
#     again": a character already done costs a Forge start and a list check, nothing is redone,
#     and no local progress file has to survive for the run to be correct.
#   * The local journal ($STATE/journal.log) only saves time inside one container: a character
#     finished here is not started again here. A new container starts with an empty journal and
#     lets the dataset decide.
#   * One run per container (a lock): two Forges at once ran out of memory (2026-11-21), and two
#     runs would publish the same character twice.
#   * A character whose run dies is retried (RETRIES, growing pause) before the next one; the
#     watchdog's stop (disk or memory low) ends the whole run instead, since retrying would only
#     hit the same wall. `status` says which of these happened.
#   * A fresh container sets itself up: the venv with the `hf` extra, the library (five CC0
#     avatars fetched against pinned hashes, the VRoid ones are committed), and renders only if
#     the chatbot is checked out beside this repository (RENDER=0 otherwise, said in the log).
#
#   HF_TOKEN=proxy-injected setsid nohup tools/populate_resume.sh run > ~/populate.log 2>&1 &
#   HF_TOKEN=proxy-injected setsid nohup tools/populate_resume.sh run avatar-sample-a vroid-rinna > ~/populate.log 2>&1 &
#   tools/populate_resume.sh status        # running? which character? what failed? last lines
#   FORGE_GRANT=… tools/populate_resume.sh count   # what the Space still misses, per character
#
# The token stays in the environment (the proxy-injected credential in a cloud session); a
# grant for `count` too. Neither is ever written to a file or a log here.
set -u
FORGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${STATE:-$HOME/.populate-failover}"
WORK="${WORK:-$STATE/work}"
RETRIES="${RETRIES:-3}"
SPACE="${SPACE:-https://ruslanmv-3d-wardrobe-forge.hf.space}"
mkdir -p "$STATE"; chmod 700 "$STATE"
JOURNAL="$STATE/journal.log"
cmd="${1:-status}"; [ "$#" -gt 0 ] && shift

log() { echo "$(date -u +%Y-%m-%dT%H:%M) $*" | tee -a "$JOURNAL"; }

setup() {
  cd "$FORGE_DIR" || return 1
  if ! .venv/bin/python -c "import huggingface_hub, pydantic_settings" 2>/dev/null; then
    log "setup: venv"
    python3 -m venv .venv && .venv/bin/pip install -q -e ".[preview,hf]" || return 1
  fi
  python3 tools/fetch_library.py > "$STATE/fetch.log" 2>&1 || { log "setup: library fetch failed (see $STATE/fetch.log)"; return 1; }
  local chatbot="${CHATBOT:-$(cd "$FORGE_DIR/.." && pwd)/3D-Avatar-Chatbot}"
  if [ ! -f "$chatbot/tools/qa/private-positions-live.mjs" ]; then
    export RENDER=0; log "setup: no chatbot at $chatbot, so no frames (RENDER=0)"
  fi
}

characters() {
  if [ "$#" -gt 0 ]; then echo "$*"; return; fi
  (cd "$FORGE_DIR" && .venv/bin/python -c "from wardrobe.config import get_settings; from wardrobe.library import AvatarLibrary
print(' '.join(a.slug for a in AvatarLibrary.from_directory(get_settings().wardrobe_library_root).available()))")
}

run() {
  : "${HF_TOKEN:?set HF_TOKEN (write access; HF_TOKEN=proxy-injected in a cloud session)}"
  exec 9>"$STATE/lock"
  flock -n 9 || { echo "already running here (lock $STATE/lock)"; exit 0; }
  setup || exit 1
  export WORK RENDERS="${RENDERS:-$WORK/renders}"
  log "run: start (pid $$)"
  for slug in $(characters "$@"); do
    if grep -q " done $slug\$" "$JOURNAL" 2>/dev/null; then echo "skip $slug: done in this container"; continue; fi
    for attempt in $(seq 1 "$RETRIES"); do
      log "start $slug (attempt $attempt)"
      out="$STATE/run-$slug.log"
      "$FORGE_DIR/tools/populate_private.sh" "$slug" > "$out" 2>&1
      if grep -q "=== WATCHDOG STOP" "$out"; then log "watchdog stop during $slug: $(grep '=== WATCHDOG STOP' "$out")"; exit 3; fi
      if grep -q "=== $slug done" "$out"; then log "done $slug"; break; fi
      log "failed $slug (attempt $attempt): $(tail -1 "$out")"
      sleep $((attempt * 120))
    done
  done
  log "run: finished"
}

status() {
  if [ -f "$STATE/lock" ] && ! flock -n "$STATE/lock" true 2>/dev/null; then echo "RUNNING"; else echo "NOT RUNNING"; fi
  echo "--- journal ($JOURNAL)"; tail -n 15 "$JOURNAL" 2>/dev/null
  local last; last=$(ls -t "$STATE"/run-*.log 2>/dev/null | head -1)
  [ -n "$last" ] && { echo "--- $last"; grep -E "^(===|---|\+|!|x) " "$last" | tail -n 12; }
  return 0
}

count() {
  : "${FORGE_GRANT:?set FORGE_GRANT (a read grant for the Space) in the environment}"
  cd "$FORGE_DIR" && .venv/bin/python tools/dataset_private_missing.py --forge "$SPACE"
}

case "$cmd" in
  run) run "$@" ;;
  status) status ;;
  count) count ;;
  *) echo "usage: $0 run [slugs…] | status | count" >&2; exit 2 ;;
esac
