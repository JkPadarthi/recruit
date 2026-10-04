# Contributing to Recruit

Thanks for wanting to help! Recruit is a small, deliberately simple project — a
CDC placement-notification PWA. The whole engine is a **deterministic mail
pipeline** (IMAP → extract → match → push) with no magic. Please keep it that
way.

This guide assumes you've read [`README.md`](./README.md) (how it works, how to
run it). Here's how to contribute cleanly.

---

## Ground rules (read this first)

1. **Never commit secrets.** `.env`, `secrets/`, and all `*.db`/backup files
   are gitignored for a reason. If you're touching config, update
   `.env.example` with descriptive placeholders — never real values. The cloud
   CI has **no** access to mailbox credentials or VAPID keys by design; don't
   sneak them in.
2. **Keep the core deterministic.** The value of Recruit is that it works
   offline and *always* matches the same mail the same way. If your change
   makes extraction/matching depend on the network or an LLM being available,
   it must **fail open**: the alert must still get delivered, even if the
   optional enhancement (e.g. a summary) is skipped.
3. **Prefer simple over clever.** "Will this still make sense in six months?"
   beats "this is elegant." One byte of well-named code > a clever one-liner.
4. **Match the existing style** (section below) so diffs stay readable.

---

## Setting up a dev environment

You do **not** need Docker to run the test suite. You need Python 3.11+ and a
venv.

```bash
# from the repo root
python3 -m venv .venv
source .venv/bin/activate

# install the app + dev/test deps (pytest, httpx, etc.)
pip install -e ".[dev]"
```

### Run the offline test suite

Tests are fully **network-stubbed** — they never touch a real mailbox, Google,
or any external LLM. So the same command that CI runs also runs locally:

```bash
python3 -m pytest -q
```

**Always run this before opening a PR.** If it's red, CI will be red too.
The project's goal is to keep `tests/` fast (currently ~51 tests, a few
seconds). Don't add a test that needs real credentials or a live network.

### Optional: run the full stack with Docker

```bash
cp .env.example .env          # fill in real values (see README §3)
docker network create proxy 2>/dev/null || true
docker compose build
docker compose up -d
```

Only do this if you actually need to exercise the IMAP/push path. For most
changes, `pytest` is enough.

---

## Coding conventions

### Layout recap (see README for more)

```
app/        FastAPI app — main.py (routes), ingest.py (IMAP poll loop),
            extract.py (parse), matcher.py (match), push.py (VAPID),
            summarize.py (optional LLM), models.py, config.py, db.py
static/     PWA frontend — app.js, style.css, sw.js
scripts/    ops — backup.py (and now restore_drill.py)
tests/      offline pytest suite (network stubbed)
compose.yml app + worker + backup containers
```

### Rules of thumb

- **`app/extract.py` owns parsing; `matcher.py` owns matching.** Don't mix
  them. A new extraction rule goes in `extract.py`; a new notification policy
  in `matcher.py`/`push.py`.
- **Metrics updates go in `app/metrics.py`**, and are bumped at the event site
  (e.g. a counter increments in `push.py` where the push actually happens).
  Gauges are recomputed from the DB on scrape — don't try to persist them.
- **Log via the existing `log = logging.getLogger(...)` pattern** with a
  context clearer, e.g. `log.info("poll: cursor=%s", ...)`. No bare `print`.
- **Type hints + docstrings on new functions.** Keep them brief; the goal is
  a reader can tell what a function does and returns in one glance.
- **Backwards-compatible DB changes only.** If you alter `app/models.py`, make
  sure an existing database still works (e.g. new columns need defaults), and
  update `scripts/restore_drill.py`'s expectations if the schema affects it.
- **Everything the image doesn't need stays out of it.** If you add a value
  that's runtime-only, route it through `.env` → `app/config.py`, and document
  it in `.env.example` and the README config table. If you add a file that's
  docs-only (like this one), remember it's **not** COPYd into the image — that
  also makes it a handy CI/CD smoke test, but don't rely on it for runtime.

---

## Making changes

1. **Create a branch** (or work on `main` if you have push access and it's a
   small change — the repo is a small project, not a rules-lawyer).

   ```bash
   git checkout -b your-feature
   ```

2. **Write the change.** Keep it focused — one concern per PR/commit.

3. **Update or add tests** in `tests/`. If you touched `extract.py`, add a
   parse test; `matcher.py`, a match test; `push.py`, a notification test.
   Stub the network, never call it.

4. **Run the suite until green:**

   ```bash
   python3 -m pytest -q      # expect: 51 passed (or green with your additions)
   ```

5. **Update docs if behavior changed** — README (config table / pipeline /
   operations) and `.env.example`. Contributing means leaving a better map.

6. **Commit with a clear message.** Conventional style:

   ```text
   recruit: add a concise summary of what and why

   - bullet points of the meaningful changes
   - note any breaking behavior or config additions
   ```

   (Prefix with the affected area — `worker`, `ingest`, `matcher`, `push`,
   `metrics`, `tests`, `ops`, etc.)

---

## CI / DD — how your change ships

Recruit runs **CI on every push** and **CD only during a fixed night window**
(22:00–00:00 IST) — "CI/DD". You don't need to do anything special; the
pipeline handles it. But you should know what happens so a push isn't a
surprise:

- **CI (GitHub Actions)** — `.github/workflows/test.yml` runs `pip install -e
  ".[dev]"` then `python -m pytest -q` in a fresh cloud runner on every push
  and PR. Watch the **Actions** tab for the ✅/❌. This runs with **no
  secrets**, so it can only catch logic/test failures — not config.
- **CD (systemd on the host)** — `scripts/cd-deploy.sh`, triggered every 5
  minutes by the `recruit-cd.timer` unit on the production box (`abhi`). It is
  a cheap no-op during the day and **only deploys between 22:00 and 00:00 IST**
  **and** when `origin/main` has actually moved (`git rev-parse` local vs
  remote differ). A `flock` lock guarantees a 5-min tick never stacks on an
  in-flight Pi-4 build.

Consequences for contributors:

- A push at 3pm runs CI immediately but **won't deploy until that night's
  window**. That's by design — daytime pushes never disturb the live app.
- If your commit is on a branch, only a merge/push to `main` triggers CD.
  CI runs on the branch too (so you get feedback before merging).
- Watch the deploy log to confirm your change landed:
  `tail -f ~/Projects/recruit/data/logs/cd.log`
  (`up to date` = nothing new; `deployed <sha>` = it shipped).

**Handy smoke test:** if you only want to verify the whole CI + CD gate loop
without touching production logic, edit `README.md` / `CONTRIBUTING.md` and
push it. Docs aren't COPYd into the image, so the night build is a full
cache hit — fast and safe — yet it still exercises CI and CD's "origin moved"
gate end to end.

---

## Testing a DB / ops change

If you changed anything that touches the SQLite schema, backup, or restore
path:

```bash
python3 scripts/restore_drill.py
```

This restores the newest backup to a throwaway DB, runs `integrity_check`,
and compares per-table counts against the live DB. It never touches live data.
A new column or table should show up there; a schema break will show up as a
mismatch.

---

## Pull requests

Small project, small ceremony:

- **Describe what & why** in the PR body (the commit message usually has it).
- **Confirm the suite is green** (CI will double-check).
- **Flag config changes** if behaviour defaults shift.
- If it's a one-line docs fix, don't over-engineer the PR — keep it lean.

---

## Questions / doing something bigger

If you're planning something structural (new container, schema migration,
changing the match policy, moving hosts) — open an issue or a draft PR **first**
and describe the intent. The project values consensus on direction before a
lot of code moves. When in doubt, ask.