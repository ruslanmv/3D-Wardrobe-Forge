#!/bin/bash
# BD29. Verify a painter change on ONE exact skin pack, seen the way a person sees it, with nothing
# reaching the dataset: a local Forge that reads the dataset but never publishes
# (WARDROBE_HF_PUBLISH=false), the pack built through the same library route a repaint uses, then
# the chatbot's own Step 5 page (tools/qa/private-positions-live.mjs) wearing exactly that look.
#
# Why (2026-11-21): a Forge started with the HF backend publishes every look it makes ("forge: N
# looks made on demand"), so a "local test" landed in the dataset; and a rebuild of a listed bare
# look is saved but never listed (bare looks are keep-existing), so a renderer picking from the list
# showed the old paint. This script avoids both: publishing off, and the look worn by its id and
# its own file's SHA-256 (--look-id / --look-sha).
#
#   tools/qa/verify_pack.sh <slug> <chatbot avatar file> <preset> <pack states> <render states> [keys] [out]
#   tools/qa/verify_pack.sh avatar-sample-a AvatarSample_A.vrm natural \
#       closed,doggy-anal-ring,doggy-anal-ring-cum doggy-anal-ring,doggy-anal-ring-cum
#
# Frames and sheet.png land in OUT (default $TMPDIR/verify-pack/<slug>), never in a repository; look
# at them (tools/qa/compare_frames.py puts two runs side by side). HF_TOKEN must be in the
# environment (reads only; proxy-injected in a cloud session). Admin token and grant are throwaway,
# owner-only files deleted on exit. Uses port 8097 (PORT=… to change); one run at a time.
set -u
SLUG="$1"; AVATAR="$2"; PRESET="$3"; PACK="$4"; SHOW="$5"
KEYS="${6:-all-fours,face-down,bent-over}"
OUT="${7:-${TMPDIR:-/tmp}/verify-pack/$SLUG}"
PORT="${PORT:-8097}"
: "${HF_TOKEN:?set HF_TOKEN (read access to the dataset) in the environment}"
FORGE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CHATBOT="${CHATBOT:-$(cd "$FORGE_DIR/.." && pwd)/3D-Avatar-Chatbot}"
WORK="$OUT/work"; mkdir -p "$WORK"; chmod 700 "$WORK"; rm -rf "$OUT/frames"
cd "$FORGE_DIR"
export WARDROBE_STORAGE_BACKEND=hf WARDROBE_HF_DATASET="${DATASET:-ruslanmv/3d-wardrobe-garments}" \
  WARDROBE_ADULT_BODY_SURFACE=true WARDROBE_HF_PUBLISH=false WARDROBE_STORAGE_ROOT="$WORK/root"
PASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
GS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(40))')
WARDROBE_ADMIN_PASSWORD="$PASS" WARDROBE_GRANT_SECRET="$GS" \
  .venv/bin/python -m uvicorn apps.api.main:app --port "$PORT" > "$WORK/forge.log" 2>&1 &
F=$!; GS=""
trap 'kill $F 2>/dev/null; rm -f "$WORK/.admin" "$WORK/.grant"' EXIT
for _ in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 1; done
curl -s -X POST "http://127.0.0.1:$PORT/v1/admin/session" -H 'content-type: application/json' \
  -d "{\"password\":\"$PASS\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' > "$WORK/.admin"
chmod 600 "$WORK/.admin"; PASS=""
STATES=$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1].split(",")))' "$PACK")
JOB=$(curl -s -X POST "http://127.0.0.1:$PORT/v1/library/$SLUG/jobs" -H "X-Wardrobe-Admin: $(cat "$WORK/.admin")" \
  -H 'content-type: application/json' \
  -d "{\"outfit\":{\"prompt\":\"Bare authored body\",\"mode\":\"template\",\"templateId\":\"body-bare-v1\"},\"options\":{\"baseBody\":\"bare\",\"renderPreview\":true,\"engine\":\"native\",\"bareDetail\":\"$PRESET\",\"bareStates\":$STATES}}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "job $JOB $(date -u +%H:%M)"
STATE=""
for _ in $(seq 1 1440); do
  STATE=$(curl -s "http://127.0.0.1:$PORT/v1/jobs/$JOB" -H "X-Wardrobe-Admin: $(cat "$WORK/.admin")" \
    | python3 -c 'import json,sys;j=json.load(sys.stdin);print(j.get("state"), (j.get("look") or {}).get("id"))')
  case "$STATE" in completed*|failed*|rejected*|cancelled*) break ;; esac
  sleep 5
done
echo "job $STATE $(date -u +%H:%M)"
case "$STATE" in completed*) ;; *) exit 1 ;; esac
LOOK=$(echo "$STATE" | awk '{print $2}')
SHA=$(sha256sum "$WORK/root/looks/$LOOK/look.vrm" | cut -c1-64)
curl -s -X POST "http://127.0.0.1:$PORT/v1/admin/grants" -H "X-Wardrobe-Admin: $(cat "$WORK/.admin")" \
  -H 'content-type: application/json' -d "{\"slugs\":[\"$SLUG\"],\"ttlSeconds\":3600,\"label\":\"verify pack\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])' > "$WORK/.grant"
chmod 600 "$WORK/.grant"
(cd "$CHATBOT" && FORGE_GRANT="$(cat "$WORK/.grant")" timeout 1500 node tools/qa/private-positions-live.mjs \
  --level5 --forge-grant --forge-url "http://127.0.0.1:$PORT" --behind ${HAIR_ASIDE:+--hair-aside} \
  --world bright-hotel --keys "$KEYS" --avatar "$AVATAR" --slug "$SLUG" --states "$SHOW" \
  --look-id "$LOOK" --look-sha "$SHA" --out "$OUT/frames" > "$OUT/render.log" 2>&1)
echo "=== rendered (exit $?) $(date -u +%H:%M): $OUT/frames/sheet.png"
grep -E "FAIL|wearing" "$OUT/render.log" || true
