#!/bin/bash
# BD32. Several exact packs verified in a row, one local Forge at a time, nothing published: each
# line of a checks file runs tools/qa/verify_pack.sh, and the frames land in OUT/<name>/frames.
#
# Why: a painter change is checked on more than one body and more than one pack (Avatar A's
# fisted, bottle and ring packs, then Avatar B), and two Forges painting at once ran out of
# memory (2026-11-21). One after another, detached, with the log telling which one is running.
#
#   tools/qa/verify_set.sh <checks file> <out dir>
#   setsid nohup tools/qa/verify_set.sh tools/qa/checks/painter.txt <scratch>/vset > <scratch>/vset.log 2>&1 &
#
# A checks file: one check per line, `#` comments, fields separated by spaces:
#   <name> <slug> <chatbot avatar file> <preset> <pack states> <render states> <positions> [hair]
# `hair` (optional) frames her with her hair aside (HA1). See tools/qa/checks/painter.txt.
# HF_TOKEN must be in the environment (reads only). Compare runs with tools/qa/compare_frames.py.
set -u
CHECKS="$1"; OUT="$2"
: "${HF_TOKEN:?set HF_TOKEN (read access to the dataset) in the environment}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
while read -r name slug avatar preset pack show keys hair; do
  case "$name" in ''|\#*) continue ;; esac
  echo "=== $name $(date -u +%H:%M)"
  HAIR_ASIDE="${hair:+1}" "$HERE/verify_pack.sh" "$slug" "$avatar" "$preset" "$pack" "$show" "$keys" "$OUT/$name"
done < "$CHECKS"
echo "=== SET DONE $(date -u +%H:%M)"
