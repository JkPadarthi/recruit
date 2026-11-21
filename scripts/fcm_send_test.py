#!/usr/bin/env python3
"""Send one real FCM push to a Recruit user — the smoke test after Firebase setup.

Run this on the prod host (abhi) inside the app container, or locally with the
service account present and FCM_SERVICE_ACCOUNT exported.

  # is push wired up at all?
  python3 scripts/fcm_send_test.py --check

  # one notification, no deadline alarm
  python3 scripts/fcm_send_test.py --email padarthi133@gmail.com

  # the full path: notification + a local alarm 91 minutes out, so the phone's
  # T-90 reminder fires about a minute from now. Lock the phone and watch.
  python3 scripts/fcm_send_test.py --email padarthi133@gmail.com --alarm-in 91
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Works both from the repo (parent of scripts/) and from a copy in /tmp inside
# the container, where the package lives at /srv/app.
for candidate in (Path(__file__).resolve().parent.parent, Path("/srv"), Path.cwd()):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app import fcm  # noqa: E402
from app.db import DB  # noqa: E402
from app.models import FcmToken, User  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report configuration and tokens")
    ap.add_argument("--email", help="recipient (defaults to the first user with a token)")
    ap.add_argument("--title", default="✅ Test push")
    ap.add_argument("--body", default="Delivered by Play Services, not Chrome")
    ap.add_argument("--alarm-in", type=int, metavar="MIN",
                    help="also schedule an alarm MIN minutes from now (91 => T-90 fires in ~1m)")
    args = ap.parse_args()

    db = DB()
    with db.session() as s:
        try:
            tokens = s.execute(select(FcmToken)).scalars().all()
        except OperationalError:
            print(f"This database has no fcm_tokens table — you are probably pointed at a "
                  f"local dev DB.\n  database_url: {db.url}\n"
                  f"Run this on the prod host instead:\n"
                  f"  ssh abhi 'docker cp ~/Projects/recruit/scripts/fcm_send_test.py recruit-app-1:/tmp/ && "
                  f"docker exec recruit-app-1 python3 /tmp/fcm_send_test.py --check'")
            return 2
        users = {u.id: u for u in s.execute(select(User)).scalars().all()}

        if args.check or not tokens:
            print(f"fcm enabled:   {fcm.enabled()}")
            print(f"service acct:  {fcm._sa_path() or '(not configured)'}")
            print(f"tokens:        {len(tokens)}")
            for t in tokens:
                u = users.get(t.user_id)
                print(f"  user {t.user_id:<3} {u.email if u else '?':<32} "
                      f"{t.platform:<8} …{t.token[-8:]}")
            if not tokens:
                print("\nNo device has registered yet. Install the app, log in, and look for")
                print("'token registration -> HTTP 200' in `adb logcat -s RecruitApi`.")
            return 0

        target = None
        for t in tokens:
            u = users.get(t.user_id)
            if args.email and u and u.email.lower() == args.email.lower():
                target = t.user_id
                break
        if target is None:
            target = tokens[0].user_id
        u = users.get(target)
        print(f"→ sending to user {target} ({u.email if u else '?'})")

        payload = {
            "title": args.title,
            "body": args.body,
            "tag": f"recruit-test-{int(dt.datetime.now().timestamp())}",
            "url": "/dashboard#hits",
            "event": "Recruit test",
            "when_iso": "",
        }
        if args.alarm_in:
            when = dt.datetime.now(IST) + dt.timedelta(minutes=args.alarm_in)
            payload["when_iso"] = when.replace(second=0, microsecond=0).isoformat()
            print(f"→ alarm armed for {payload['when_iso']} (T-90 / T-30 in the app)")

        stats = fcm.send(s, {target: payload})
    print(f"result: {stats}")
    return 0 if stats.get("sent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
