# Recruit

A CDC **placement-notification PWA** for VIT: it watches a CDC placement mailbox
over IMAP, extracts shortlists & registration/test announcements, matches
register IDs to users, and fires **Web Push** notifications so students find out
the moment they're shortlisted.

Stack: **FastAPI + SQLite + VAPID Web Push**, deployed as Docker Compose (3
containers: `app`, `worker`, `backup`).

> **Never commit secrets.** `.env` and `secrets/` are gitignored. The repo
> contains code + a sanitized `.env.example` only — anyone cloning it gets the
> engine, not your mailbox credentials or push keys.

---

## 1. How the mail-receiving pipeline works

The engine is simple and deterministic — no magic:

```
CDC mailbox ──IMAP──▶ app/ingest.py  ──▶ app/extract.py ──▶ matching ──▶ push
 (imap.gmail.com)     poll worker     (parse body)       (matcher.py)   (web-push)
```

1. **`worker.py`** starts a `recruit-worker` container that loops `poll_once(db)`
   every `POLL_INTERVAL_MIN` minutes (default 3).
2. **`app/ingest.py` → `connect()`** logs into the IMAP server with
   `CDC_MAILBOX_USER` + `CDC_MAILBOX_TOKEN`.
3. It tracks a **UID cursor** and only fetches *new* messages
   (`UID {last_uid+1}:*`) — so restarting never re-processes old mail.
   On first ever poll it sets a **baseline** at the highest existing UID (it
   does **not** ingest the entire backlog).
4. Each new message is parsed by **`app/extract.py`**: it pulls the subject,
   body, any links, register IDs, and the *Eligible Branches* window.
5. **`app/matcher.py`** matches extracted register IDs against users, and
   `app/push.py` blasts a targeted VAPID push per the notification policy.
6. Everything lands in SQLite tables (`ingested` = feed, `hits` = per-user
   matches, `users`, `push_subscriptions`, `entries`).

The whole pipeline is **stubbed in tests** so the offline test suite never
touches the real network:

```bash
python3 -m pytest -q
```

---

## 2. Getting it running

### Prerequisites
- Docker + Docker Compose
- An IMAP mailbox + app-password (for Gmail: Google account → Security →
  2-Step Verification → App passwords — the 16-char password is
  `CDC_MAILBOX_TOKEN`; `CDC_MAILBOX_USER` is the full email).
- VAPID keys for Web Push:

```bash
npx web-push generate-vapid-keys
```

### Setup
```bash
cp .env.example .env
# edit .env — set real values (see table below)

# create the external network the compose file expects
docker network create proxy 2>/dev/null || true

# build + run (all 3 services)
docker compose build
docker compose up -d
```

The web app listens on **port 8090**. Put it behind a reverse proxy / Cloudflare
tunnel to serve it at a real HTTPS URL (required for Web Push + Secure cookies).

### Verify
```bash
curl -s http://127.0.0.1:8090/health          # -> ok
docker logs recruit-worker-1 --tail 20        # -> "poll: ... cursor=NNNN"
docker ps --filter name=recruit               # app (healthy), worker, backup
```

Run the offline suite from the source checkout (not the container):

```bash
python3 -m pytest -q
```

---

## 3. Configuration — every knob in `.env`

| Variable | Purpose | Empty/off means |
|---|---|---|
| `SECRET_KEY` | Signs session cookies + passwords. **Set to a long random string.** | insecure auth |
| `SESSION_SECURE` | `1` = cookies are Secure-only (HTTPS only) | insecure over plain HTTP |
| `PUBLIC_BASE_URL` | Your public URL (used for links, PWA, push) | — |
| `ADMIN_EMAIL` | Email address that becomes `is_admin` on register | no admin |
| `ALLOWED_EMAIL_DOMAINS` | Comma list of domains allowed to register (`vit.ac.in,...`) | anyone can register |
| `INVITE_CODE` | Optional registration invite code | open registration |
| `CDC_MAILBOX_USER` | IMAP login (email) | **worker won't start polling** |
| `CDC_MAILBOX_TOKEN` | IMAP password / app-password (spaces stripped) | **worker won't start polling** |
| `IMAP_HOST` | IMAP server (`imap.gmail.com`) | defaults to Gmail |
| `IMAP_PORT` | IMAP port (`993`) | defaults to 993 |
| `POLL_INTERVAL_MIN` | Minutes between polls | longer = slower notifications |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | Web Push signing keys | push disabled, app still works |
| `VAPID_SUBJECT` | `mailto:` identifier for the push app | push may be refused |
| `SUMMARIZE_ENABLED` `LLM_*` | Optional LLM summaries over feed | summaries off (deterministic core runs either way) |
| `ENABLE_DEV_ENDPOINT` | Dev-only test endpoints — **keep `0` in prod** | safer |
| `DATABASE_URL` / `LOG_DIR` / `DB_BACKUP_DIR` | Paths; preset by the Dockerfile to `/data/...` | — |

---

## 4. **Pointing it at a DIFFERENT mailbox** (the question everyone asks)

You do **not** touch any code — everything is `.env`-driven.

```ini
#.env
CDC_MAILBOX_USER=your.new.mailbox@gmail.com
CDC_MAILBOX_TOKEN=your-new-app-password
IMAP_HOST=imap.gmail.com      # or imap.outlook.com, etc.
IMAP_PORT=993
POLL_INTERVAL_MIN=3
```

Then restart the worker:

```bash
docker compose up -d --force-recreate worker
```

### What changes & what doesn't
- **The mailbox it watches** → changes (the whole point).
- **The extraction/matching/push logic** → unchanged; it's generic, mailbox-agnostic.
- **A different IMAP provider** (Outlook, Yahoo, Exchange…) → just change
  `IMAP_HOST`/`IMAP_PORT`. The code uses Python's standard `imaplib` over SSL,
  so any IMAP server works. You may also need to allow "less secure apps" or an
  app-password on that provider.
- **Tracking a brand-new mailbox** → the worker baselines on first run (starts
  from the mailbox's current high UID), so it won't ingest the mailbox's old
  backlog. Point `IMAP_HOST` anywhere and it just starts listening for new mail.

> ⚠️ **One live-ops warning:** never run **two pollers against the same mailbox
> at once** (e.g. old + new host during a migration). Their UID cursors race and
> mail can be double-processed. Stop the old one before starting the new.

---

## Docker services

| Service | Image | Runs | Purpose |
|---|---|---|---|
| `recruit-app` | `recruit` | uvicorn :8090 | web app + API + PWA, healthchecked |
| `recruit-worker` | `recruit` | `python worker.py` | IMAP poll loop |
| `recruit-backup` | `recruit` | nightly `scripts/backup.py` | online SQLite backup into `./data/backups`, keeps last 14 |

All mount `./data:/data` (DB, logs, backups) and `./secrets:/run/secrets:ro`,
and sit on the external `proxy` network.

---

## Project layout

```
app/            FastAPI app: main.py (routes), ingest.py (IMAP poll),
                extract.py (parse), matcher.py (match), push.py (VAPID),
                summarize.py (LLM), models.py, config.py, security.py,
                db.py, web.py, templates/, util.py
static/         PWA: app.js, style.css, sw.js, icons
scripts/        backup.py
tests/          offline test suite (network stubbed)
compose.yml     app + worker + backup
Dockerfile      non-root runtime, /data mounted volumes
.env.example    sanitized config template (copy to .env)
```

## Operations
- **Why did X ping / not ping?** — `docker exec recruit-app-1 python3 -c "..."` to
  inspect the SQLite tables (`users`, `ingested`, `hits`, `push_subscriptions`).
- **Force a poll now** — via the admin "poll now" endpoint (admin panel).
- **Migration / rehost** — copy the whole project *including* `data/`
  (the live DB) and `secrets/`, then bring the stack up; see §4 warning about
  not dual-polling.

## CI / CD — deploy on green push, with a seatbelt

- **CI** — GitHub Actions (`.github/workflows/test.yml`) runs the offline `pytest`
  suite on every push/PR. Green/red check on the repo; no secrets needed.
- **CD** — `scripts/cd-deploy.sh`, driven by the `recruit-cd.timer` systemd unit
  on the production host **abhi**, every 5 minutes. When `origin/main` moves it
  **pulls + rebuilds + restarts** (no fixed window). `flock` serializes so a
  5-min tick never collides with an in-flight Pi-4 build.

### The seatbelt (safety rails on an auto-deploy)
- **CI-green gate** — drop a read-only GitHub token at
  `secrets/github_ci_token` (fine-grained: *Actions: read*, *Contents: read*)
  and CD only deploys when that commit's Actions run is **green**. Without the
  token it still deploys but logs a loud `WARN: … WITHOUT a CI gate`.
- **Per-SHA image tags** — every build is tagged `recruit:<short-sha>` in
  addition to `recruit:latest`, so a bad deploy has something to fall back to.
- **Health gate + auto-rollback** — after `up`, the script waits for
  `recruit-app-1` to report `healthy`; if it doesn't, it **re-tags the last
  known-good image** (recorded in `data/logs/last_good`) as `latest` and
  recreates. A failed deploy never silently stays live.
- **Opt-in quiet hours** — `touch data/logs/night_only` restores the old
  **22:00–00:00 IST-only** window (for a sensitive/exam period you want frozen).
  Remove the file to go back to deploy-on-push.
- **Hotfix escape hatch** — for an urgent fix:
  ```bash
  scripts/cd-deploy.sh --force   # skip quiet-hours + CI gate, deploy now
  touch data/logs/cd.force       # or arm the next 5-min tick (no SSH)
  ```
  `--force` skips quiet-hours and the CI gate but still health-gates + rolls
  back.

### Watching it
```bash
tail -f ~/Projects/recruit/data/logs/cd.log
# up to date (abc1234)            -> nothing new
# CI green for abc1234            -> gate passed
# deploy abc1234 -> abc1234       -> deploying
# deployed abc1234 (healthy)      -> success
# HEALTH FAILED … / rolled back … -> the seatbelt caught a bad deploy
```