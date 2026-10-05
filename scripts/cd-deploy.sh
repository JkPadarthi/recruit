#!/usr/bin/env bash
# Recruit CI/CD — deploy on push to main, with a seatbelt.
#
# Behaviour:
#   * Deploys automatically when origin/main moves (no night-window gate).
#   * CI gate: if secrets/github_ci_token exists, the pushed commit's GitHub
#     Actions run must be GREEN before we deploy (a private repo needs a token
#     to read check-runs). Without the token it proceeds with a loud WARN.
#   * Per-SHA image tag (recruit:<sha>) so we can roll back.
#   * Post-deploy HEALTH GATE on recruit-app-1; if unhealthy -> AUTO-ROLLBACK
#     to the last known-good tag (data/logs/last_good).
#   * OPT-IN quiet hours: `touch data/logs/night_only` restores the old
#     22:00-00:00-only window (for a sensitive/exam period you want frozen).
#
# Escape hatches:
#   scripts/cd-deploy.sh --force   # hotfix: skip quiet-hours + CI gate, deploy now
#   touch data/logs/cd.force       # arm the next 5-min tick the same way
#
# Driven by recruit-cd.timer (every 5 min). Logs every decision to data/logs/cd.log.
set -euo pipefail

REPO="${HOME}/Projects/recruit"
LOG="${REPO}/data/logs/cd.log"
LOCK="${REPO}/data/logs/cd.lock"
FORCE_FILE="${REPO}/data/logs/cd.force"
QUIET_FILE="${REPO}/data/logs/night_only"
LASTGOOD="${REPO}/data/logs/last_good"
TOKEN_FILE="${REPO}/secrets/github_ci_token"
REPO_SLUG="JkPadarthi/recruit"
APP="recruit-app-1"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# --- forced (hotfix) deploy? ---
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
[ -f "$FORCE_FILE" ] && FORCE=1

# --- optional quiet hours (opt-in; default OFF = deploy any time) ---
now_h="$(TZ=Asia/Kolkata date +%H)"
if [ "$FORCE" -eq 0 ] && [ -f "$QUIET_FILE" ] && [ "$now_h" -lt 22 ]; then
    log "skip: quiet-hours (hour=$now_h, data/logs/night_only set)"; exit 0
fi

# Serialize deploys: a 5-min timer must never collide with an in-flight build.
exec 9>"$LOCK"
flock -n 9 || { log "skip: a deploy is already running"; exit 0; }

cd "$REPO"
git fetch --quiet origin main 2>>"$LOG" || true
local="$(git rev-parse HEAD)"
remote="$(git rev-parse origin/main)"

if [ "$local" = "$remote" ] && [ "$FORCE" -eq 0 ]; then
    log "up to date (${local:0:7})"; rm -f "$FORCE_FILE"; exit 0
fi

# target the remote SHA (or current HEAD on a forced redeploy)
if [ "$local" != "$remote" ]; then
    target_full="$remote"
else
    target_full="$local"
fi
short="${target_full:0:7}"

# --- CI gate (require green) ---
if [ "$FORCE" -eq 0 ]; then
    if [ -f "$TOKEN_FILE" ]; then
        tok="$(cat "$TOKEN_FILE")"
        concl="$(curl -fsS -H "Authorization: token $tok" \
            "https://api.github.com/repos/$REPO_SLUG/commits/$target_full/check-runs" 2>/dev/null \
            | python3 -c 'import sys,json
d=json.load(sys.stdin); runs=d.get("check_runs",[])
print("pending" if not runs or any(r.get("status")!="completed" for r in runs)
      else ("failure" if any(r.get("conclusion") not in ("success","skipped","neutral") for r in runs)
      else "success"))' 2>/dev/null || echo unknown)"
        if [ "$concl" != "success" ]; then
            log "skip: CI not green for $short (=$concl)"; exit 0
        fi
        log "CI green for $short"
    else
        log "WARN: no $TOKEN_FILE — deploying $short WITHOUT a CI gate"
    fi
fi

log "${FORCE:+FORCED }deploy ${local:0:7} -> $short"
git pull --ff-only --quiet origin main 2>>"$LOG" || true

if ! docker compose build app worker >>"$LOG" 2>&1; then
    log "build FAILED — leaving the running version untouched"; exit 1
fi
docker tag recruit:latest "recruit:$short" >>"$LOG" 2>&1 || true

prev=""; [ -f "$LASTGOOD" ] && prev="$(cat "$LASTGOOD")"

docker compose up -d --force-recreate app worker >>"$LOG" 2>&1

# --- health gate ---
st="unknown"
for _ in $(seq 1 30); do
    sleep 3
    st="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' "$APP" 2>/dev/null || echo missing)"
    [ "$st" = "healthy" ] && break
done

if [ "$st" = "healthy" ]; then
    printf '%s\n' "$short" > "$LASTGOOD"
    log "deployed $short (healthy)"
    rm -f "$FORCE_FILE"; exit 0
fi

# --- auto-rollback ---
log "HEALTH FAILED for $short (status=$st)"
if [ -n "$prev" ] && [ "$prev" != "$short" ] && docker image inspect "recruit:$prev" >/dev/null 2>&1; then
    log "rollback -> $prev"
    docker tag "recruit:$prev" recruit:latest >>"$LOG" 2>&1
    docker compose up -d --force-recreate app worker >>"$LOG" 2>&1
    log "rolled back to $prev"
else
    log "no known-good image to roll back to; $short left in place (investigate)"
fi
rm -f "$FORCE_FILE"
exit 1