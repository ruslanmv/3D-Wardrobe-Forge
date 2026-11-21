#!/bin/bash
# PV1. Build every private look and every After Dark outfit for every character, one character at
#      a time, publish it to the dataset, and render her from behind (all fours, face down with
#      hips up, bent over) in the chatbot's own viewer before moving on.
#
# Why this shape (2026-11-21, after building Avatar A's fist and gape packs by hand):
#   * One character per fresh Forge process (as tools/populate_dataset.sh, DS1): a pack of ten
#     states holds ~5 GB while it paints, so Forge is never left to pile up memory across eight
#     characters; the character's local files are deleted once they are published.
#   * The from-behind packs first (BEHIND_GROUPS: the doggy, back, fist and gape-after-bottle
#     states, plus the core ones every evening needs), published at once, then rendered: the
#     collection people ask for from behind is in the dataset after the first ~hour, not the last.
#   * Then the rest of her private set (every other group, the extras sets, After Dark · Bare) and
#     the outfit dictionary (After Dark and the erotic sets, prebuild.py --outfits-only), each
#     published as soon as it is built. Everything is --missing-only / not --overwrite: a look the
#     dataset lists is never sent again and never replaced (PB7), so a stopped run resumes.
#   * The render is the chatbot's real page (tools/qa/private-positions-live.mjs) against THIS
#     Forge, with a one-hour read grant minted by it (a throwaway grant secret, never printed), so
#     what is checked is what was just built, before the Space has picked it up. Frames go to
#     RENDERS (outside both repositories); none is ever committed.
#   * A watchdog stops the run cleanly under MIN_DISK_GB free disk or MIN_MEM_MB available memory.
#   * Detail clearance comes from the reviews in the dataset (RX3: restored at Forge start); a
#     character without it is refused by Forge's own gate and reported, never worked around.
#
# Needs: HF_TOKEN in the environment (write access; never in a file, commit or log; in a cloud
# session with the proxy-injected credential, HF_TOKEN=proxy-injected), `.venv` with
# `pip install -e ".[hf]"`, the library on disk (`tools/fetch_library.py`), and the chatbot checked
# out beside this repository with its `npm ci` done (CHATBOT=… to point elsewhere).
#
#   HF_TOKEN=… tools/populate_private.sh                          # every character, everything
#   HF_TOKEN=… tools/populate_private.sh avatar-sample-b          # some
#   HF_TOKEN=… PHASES=behind tools/populate_private.sh            # only the from-behind packs
#   HF_TOKEN=… RENDER=0 tools/populate_private.sh                 # build and publish, no frames
#   HF_TOKEN=… PHASES=repaint REPAINT_BEFORE=2026-11-21T09:00 tools/populate_private.sh a b   # BD25
#   Run it detached and watch the log: setsid nohup tools/populate_private.sh > run.log 2>&1 &
#
# BD25 (`repaint`, first when asked): the listed detailed looks built before REPAINT_BEFORE whose
# states open her anus are painted again with the fixed painter (BD24 `_behind_mask`: no more red
# streaks down her inner thighs) and published with --overwrite, replacing exactly those looks and
# nothing else. REPAINT_SKIP lists characters left alone (vroid-rinna until her bare looks strip).
set -u
: "${HF_TOKEN:?set HF_TOKEN (write access to the dataset) in the environment}"
FORGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHATBOT="${CHATBOT:-$(cd "$FORGE_DIR/.." && pwd)/3D-Avatar-Chatbot}"
WORK="${WORK:-${TMPDIR:-/tmp}/populate-private}"
RENDERS="${RENDERS:-$WORK/renders}"
PORT="${PORT:-8096}"
DATASET="${DATASET:-ruslanmv/3d-wardrobe-garments}"
PRESETS="${PRESETS:-natural}"
PHASES="${PHASES:-repaint,behind,private,outfits}"
# BD29 (2026-11-21 10:28 UTC): the crotch landmark fix that ended the red bands down her inner
# thighs. Every listed detailed look opening her anus built before it is repainted first. If the
# Space built bare looks after that time but before it was deployed with the fix, pass the
# deploy time instead.
REPAINT_BEFORE="${REPAINT_BEFORE:-2026-11-21T10:30}"
REPAINT_SKIP="${REPAINT_SKIP:-vroid-rinna}"
RENDER="${RENDER:-1}"
MIN_DISK_GB="${MIN_DISK_GB:-3}"
MIN_MEM_MB="${MIN_MEM_MB:-1500}"
# BD28 ring, BD34 the two lighter mark strengths (rough-soft is "Legata e spalancata"'s default),
# BD35 two hands (fist-wide). The Prebuild workflow builds every group already (no --groups).
BEHIND_GROUPS="${BEHIND_GROUPS:-core,doggy,back,fist,fist-wide,ring,bottle,rough-soft,rough-light,rough}"
REST_GROUPS="${REST_GROUPS:-oiled,missionary,cowgirl,unrestrained,other}"
# What the frames show on each position: her fisted states and the gape filled after them.
STATES="${STATES:-doggy-anal-fisted,doggy-anal-fisted-cum,doggy-both-fisted-cum}"
mkdir -p "$WORK" "$RENDERS"; chmod 700 "$WORK"
cd "$FORGE_DIR"
if [ "$#" -gt 0 ]; then SLUGS="$*"; else
  SLUGS=$(.venv/bin/python -c "from wardrobe.config import get_settings; from wardrobe.library import AvatarLibrary
print(' '.join(a.slug for a in AvatarLibrary.from_directory(get_settings().wardrobe_library_root).available()))")
fi
export HF_TOKEN WARDROBE_STORAGE_BACKEND=hf WARDROBE_HF_DATASET="$DATASET" WARDROBE_ADULT_BODY_SURFACE=true

# The chatbot's file for each library character (its vendor/avatars, which declares them adult).
avatar_file() {
  case "$1" in
    avatar-sample-a) echo AvatarSample_A.vrm ;; avatar-sample-b) echo AvatarSample_B.vrm ;;
    avatar-sample-c) echo AvatarSample_C.vrm ;; fem-vroid) echo fem_vroid.vrm ;;
    masc-vroid) echo masc_vroid.vrm ;; vroid-avatar-sample-o) echo AvatarSample_O.vrm ;;
    vroid-model-girl) echo Model_Girl.vrm ;; vroid-rinna) echo Rinna.vrm ;; *) echo "" ;;
  esac
}

stop_all() { pkill -f "uvicorn apps.api.main:app --port $PORT"; pkill -f "tools/prebuild(_private)?.py --forge http://127.0.0.1:$PORT"; }

watchdog() {
  while sleep 30; do
    disk=$(df -Pk "$WORK" | tail -1 | awk '{print $4}'); mem=$(free -m | awk '/Mem:/{print $7}')
    if [ "$disk" -lt $((MIN_DISK_GB * 1024 * 1024)) ] || [ "$mem" -lt "$MIN_MEM_MB" ]; then
      echo "=== WATCHDOG STOP $(date -u +%H:%M): ${disk} KB disk, ${mem} MB memory"; touch "$WORK/.stop"; stop_all; return
    fi
  done
}
rm -f "$WORK/.stop"; watchdog & WATCH=$!; trap 'kill $WATCH 2>/dev/null; stop_all; rm -f "$WORK/.admin" "$WORK/.grant"' EXIT

publish() { # $1 slug, $2 what, $3 "--overwrite" for a repaint (replaces exactly this run's looks)
  if [ -d "$WARDROBE_STORAGE_ROOT/prebuilt" ]; then
    .venv/bin/python tools/publish_prebuilt.py --root "$WARDROBE_STORAGE_ROOT" ${3:-} \
      --message "prebuild: $1 $2 (${3:+repainted, }missing only)"
    echo "--- $1 $2 published (exit $?)"
  fi
}

# Her from behind (all fours, face down, bent over) in the chatbot's own viewer against THIS Forge,
# her hair aside (HA1) so nothing covers what was just painted. Once per character.
render() { # $1 slug
  local slug="$1" file; file=$(avatar_file "$slug")
  [ "$RENDER" = 1 ] && [ -n "$file" ] && [ -d "$CHATBOT" ] || return 0
  curl -s -X POST "http://127.0.0.1:$PORT/v1/admin/grants" -H "X-Wardrobe-Admin: $(cat "$WORK/.admin")" \
    -H 'content-type: application/json' -d "{\"slugs\":[\"$slug\"],\"ttlSeconds\":3600,\"label\":\"populate render\"}" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' > "$WORK/.grant"
  chmod 600 "$WORK/.grant"
  (cd "$CHATBOT" && FORGE_GRANT="$(cat "$WORK/.grant")" timeout 1500 node tools/qa/private-positions-live.mjs \
    --level5 --forge-grant --forge-url "http://127.0.0.1:$PORT" --behind --hair-aside --world bright-hotel \
    --keys all-fours,face-down,bent-over --avatar "$file" --slug "$slug" --states "$STATES" \
    --out "$RENDERS/$slug" > "$RENDERS/$slug.log" 2>&1)
  echo "--- $slug rendered (exit $?): $RENDERS/$slug/sheet.png"
  rm -f "$WORK/.grant"
}

has() { case ",$PHASES," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

for slug in $SLUGS; do
  [ -f "$WORK/.stop" ] && break
  echo "=== $slug start $(date -u +%H:%M)"
  export WARDROBE_STORAGE_ROOT="$WORK/root-$slug"
  # Throwaway secrets for this Forge only: never printed, gone when the loop moves on.
  PASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
  GRANT_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(40))')
  WARDROBE_ADMIN_PASSWORD="$PASS" WARDROBE_GRANT_SECRET="$GRANT_SECRET" \
    .venv/bin/python -m uvicorn apps.api.main:app --port "$PORT" > "$WORK/forge-$slug.log" 2>&1 &
  FORGE=$!; GRANT_SECRET=""
  for i in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 1; done
  curl -s -X POST "http://127.0.0.1:$PORT/v1/admin/session" -H 'content-type: application/json' \
    -d "{\"password\":\"$PASS\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' > "$WORK/.admin"
  chmod 600 "$WORK/.admin"; PASS=""
  B="--forge http://127.0.0.1:$PORT --admin-token-file $WORK/.admin --slugs $slug --workers 1"

  if has repaint && [ -n "$REPAINT_BEFORE" ] && ! case ",$REPAINT_SKIP," in *",$slug,"*) true;; *) false;; esac; then
    .venv/bin/python tools/prebuild_private.py $B --repaint-before "$REPAINT_BEFORE" \
      --job-timeout "${JOB_TIMEOUT:-3600}" --report "$WORK/report-$slug-repaint.json"
    publish "$slug" "repainted looks" --overwrite
    # What was repainted is published; the phases below publish missing-only from a clean root.
    rm -rf "$WARDROBE_STORAGE_ROOT/prebuilt"
  fi
  if has behind && [ ! -f "$WORK/.stop" ]; then
    .venv/bin/python tools/prebuild_private.py $B --presets "$PRESETS" --groups "$BEHIND_GROUPS" \
      --extras-sets none --bare-looks none --job-timeout "${JOB_TIMEOUT:-3600}" --report "$WORK/report-$slug-behind.json"
    publish "$slug" "behind packs"
  fi
  if (has repaint || has behind) && [ ! -f "$WORK/.stop" ]; then render "$slug"; fi
  if has private && [ ! -f "$WORK/.stop" ]; then
    .venv/bin/python tools/prebuild_private.py $B --presets "$PRESETS" --groups "$REST_GROUPS" --job-timeout "${JOB_TIMEOUT:-3600}" \
      --report "$WORK/report-$slug-private.json"
    publish "$slug" "private looks"
  fi
  if has outfits && [ ! -f "$WORK/.stop" ]; then
    .venv/bin/python tools/prebuild.py $B --outfits-only --missing-only --job-timeout 900 \
      --report "$WORK/report-$slug-outfits.json"
    publish "$slug" "outfits"
  fi
  kill "$FORGE" 2>/dev/null; wait "$FORGE" 2>/dev/null; rm -f "$WORK/.admin"
  rm -rf "$WARDROBE_STORAGE_ROOT"
  echo "=== $slug done $(date -u +%H:%M) · disk free $(df -h "$WORK" | tail -1 | awk '{print $4}')"
done
echo "=== ALL DONE $(date -u +%H:%M) · reports in $WORK/report-*.json, frames in $RENDERS"
