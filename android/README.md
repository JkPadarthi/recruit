# Recruit Android shell

A thin WebView around the existing dashboard, plus the two things a browser cannot do:

| Capability | Why the PWA can't |
|---|---|
| **FCM high-priority push** | Web Push rides Chrome. Android is free to freeze Chrome, and a frozen browser cannot decrypt the message — this cost 3.5 hours on the HCL shortlist. FCM is delivered by Play Services, a *system* component, which is exempt from Doze and can start a killed app. |
| **Exact local alarms** | Chrome prototyped scheduled notifications (`showTrigger`/`TimestampTrigger`) and never shipped it. On Android the app schedules `AlarmManager.setExactAndAllowWhileIdle` from your own sheet row, so the reminder fires at the exact minute with no network at all. |

The web app remains the source of truth. This shell only adds delivery.

---

## 1. Firebase project (one time, ~10 minutes)

1. <https://console.firebase.google.com> → **Add project** → name it `recruit` (Analytics not needed).
2. In the project: **Add app** → **Android**.
   - Package name: `com.jkpadarthi.recruit` (debug builds use `.debug`, which is fine).
   - Download **`google-services.json`** and drop it at `android/app/google-services.json`.
3. Project settings (⚙) → **Service accounts** → **Generate new private key**.
   That JSON is the *server* credential. Rename it `fcm_service_account.json` and put it on
   `abhi` at `~/Projects/recruit/secrets/fcm_service_account.json` (that directory is already
   mounted read-only into the container as `/run/secrets`).
4. On `abhi`, add to `~/Projects/recruit/.env`:
   ```
   FCM_SERVICE_ACCOUNT=/run/secrets/fcm_service_account.json
   ```
   then `docker compose up -d` in `~/Projects/recruit`.
   Check: `curl -s https://recruit.98487840.xyz/api/status | jq .fcm_enabled` → `true`.

> Cloud Messaging does not have to be "enabled" anywhere — adding the Android app is enough.
> No billing account is involved; FCM is free.

## 2. Build and install

The project needs the Android SDK, so build it on the Mac (not on `bharat`):

```bash
cd android
# Open this folder in Android Studio (it will offer to create the Gradle wrapper),
# or with a local wrapper:
gradle wrapper --gradle-version 8.9
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Then: open the app → log in to Recruit inside it → watch the logs for
`RecruitApi: token registration -> HTTP 200`.

## 3. What the app does on first run

1. Asks for **notifications** (`POST_NOTIFICATIONS`, Android 13+).
2. Schedules nothing yet; asks for **exact alarms** the first time a real deadline arrives
   (`SCHEDULE_EXACT_ALARM`, denied by default on Android 14+).
3. Once, asks to be exempted from **battery optimisation** — this is the prompt every
   messaging app shows, and the answer to "why does MIUI freeze other apps".

## 4. Payload contract (server → app)

The server sends **data-only** messages, so the app is the single place that builds the
notification (no duplicates) and can schedule alarms from the same payload:

```json
{
  "title": "✅ You're on the list",
  "body": "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713",
  "tag": "recruit-983",
  "url": "/dashboard#hits",
  "when_iso": "2026-11-23T14:30:00+05:30",
  "event": "HCL Tech Online Test"
}
```

`when_iso` is empty when the sheet row has no readable date **and** time — a guessed alarm is
worse than none. When present, the app schedules reminders at **T-90** and **T-30** minutes,
which survive reboot (`BootReceiver`) and fire in Doze.

## 5. Test without waiting for a CC mail

Firebase console → **Messaging** → *Create campaign* → *Firebase Notification messages*, or:

```bash
# from bharat, with the service account handy
python3 - <<'PY'
import sys; sys.path.insert(0, "/home/Bunny/Projects/recruit")
from app.db import DB
from app import fcm
db = DB(); s = db.session()
print(fcm.send(s, {1: {
    "title": "Test deadline",
    "body": "Reporting at PRP 713",
    "tag": "recruit-test",
    "url": "/dashboard#hits",
    "when_iso": "2026-11-23T14:30:00+05:30",
    "event": "HCL Tech Online Test",
}}))
PY
```

**The real test**: force-stop Chrome, lock the phone, trigger a send, and time it.

## 6. Play Store, later

`$25` one-time → **internal testing** track: up to 100 testers by email, no review, and it
avoids Google's 12-testers/14-days gate for new personal developer accounts. FCM works on a
sideloaded APK too, so nothing is blocked on this.
