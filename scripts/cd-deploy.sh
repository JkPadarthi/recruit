#!/usr/bin/env bash
# Recruit CD gate — deploy ONLY between 22:00 and 00:00 IST, UNLESS forced.
#
# Usage:
#   scripts/cd-deploy.sh             # normal: timer-driven, night-window gated
#   scripts/cd-deploy.sh --force     # URGENT hotfix: bypass the window AND the
#                                    #   up-to-date check; rebuild+restart HEAD now
#   touch data/logs/cd.force         # arm the NEXT timer tick to bypass the
#                                    #   window once (no SSH needed); consumed on use
#
# A systemd timer runs this every 5 min. During the day it is a cheap no-op,
# so daytime pushes wait for the window. --force / the sentinel are the escape
# hatch for a live bug fix that must not wait until 22:00.
set -euo pipefail

REPO="${HOME}/Projects/recruit"
LOG="${REPO}/data/logs/cd.log"
FORCE_FILE="${REPO}/data/logs/cd.force"

# --- is this a forced (out-of-window) deploy? ---
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
[ -f "$FORCE_FILE" ] && FORCE=1          # sentinel arms the next tick

now_h="$(TZ=Asia/Kolkata date +%H)"
if [ "$FORCE" -eq 0 ] && [ "$now_h" -lt 22 ]; then
    echo "$(date '+%F %T') skip: outside night window (hour=$now_h)" >> "$LOG"
    exit 0
fi

# Serialize deploys: a 5-min timer must never collide with an in-flight build.
exec 9>"$REPO/data/logs/cd.lock"
flock -n 9 || { echo "$(date '+%F %T') skip: a deploy is already running" >> "$LOG"; exit 0; }

cd "$REPO"
git fetch --quiet origin main 2>>"$LOG" || true
local="$(git rev-parse HEAD)"
remote="$(git rev-parse origin/main)"

if [ "$FORCE" -eq 1 ]; then
    # Force: deploy current HEAD now, even if nothing new (rebuild + restart).
    echo "$(date '+%F %T') FORCED deploy (out-of-window) HEAD=${local:0:7} remote=${remote:0:7}" >> "$LOG"
    git pull --ff-only --quiet origin main 2>>"$LOG" || true
    local="$(git rev-parse HEAD)"
    docker compose build app worker >>"$LOG" 2>&1
    docker compose up -d --force-recreate app worker >>"$LOG" 2>&1
    echo "$(date '+%F %T') deployed ${local:0:7} (forced)" >> "$LOG"
    rm -f "$FORCE_FILE"
    exit 0
fi

if [ "$local" = "$remote" ]; then
    echo "$(date '+%F %T') up to date (${local:0:7})" >> "$LOG"
    rm -f "$FORCE_FILE"
    exit 0
fi

echo "$(date '+%F %T') night-window deploy ${local:0:7} -> ${remote:0:7}" >> "$LOG"
git pull --ff-only --quiet origin main 2>>"$LOG" || true
docker compose build app worker >>"$LOG" 2>&1
docker compose up -d --force-recreate app worker >>"$LOG" 2>&1
echo "$(date '+%F %T') deployed ${remote:0:7}" >> "$LOG"
rm -f "$FORCE_FILE"