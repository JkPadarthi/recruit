#!/usr/bin/env bash
# Recruitment CD gate — deploy ONLY between 22:00 and 00:00 IST (night window).
# A systemd timer runs this every 5 min. It:
#   1. skips unless we're inside the night window,
#   2. fetches origin/main, and if it moved, pulls + rebuilds + restarts.
# During the day it is a cheap no-op, so daytime pushes wait for the window.
set -euo pipefail

REPO="${HOME}/Projects/recruit"
LOG="${REPO}/data/logs/cd.log"

now_h="$(TZ=Asia/Kolkata date +%H)"
if [ "$now_h" -lt 22 ]; then
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
if [ "$local" = "$remote" ]; then
    echo "$(date '+%F %T') up to date (${local:0:7})" >> "$LOG"
    exit 0
fi

echo "$(date '+%F %T') night-window deploy ${local:0:7} -> ${remote:0:7}" >> "$LOG"
# build in the background session's shell is fine here; pull is fast
git pull --ff-only --quiet origin main 2>>"$LOG" || true
docker compose build app worker >>"$LOG" 2>&1
docker compose up -d --force-recreate app worker >>"$LOG" 2>&1
echo "$(date '+%F %T') deployed ${remote:0:7}" >> "$LOG"