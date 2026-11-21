"""A calendar file for one shortlist row.

Why this exists: an iPhone cannot run our app without a paid Apple account, and
Safari has no local-alarm API at all. An `.ics` with a VALARM is the only reminder
that works on iOS for nothing — Calendar fires it natively, whether or not the
dashboard is ever opened, and it survives the PWA being deleted.

The alarm is deliberately 90 minutes before the reporting time, matching the app's
T-90 notification. Times are written in UTC: a TZID would require shipping a
VTIMEZONE block, and getting that wrong silently shifts the event by 5:30 in the
one place a student cannot afford a wrong time.
"""
from __future__ import annotations

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _esc(text: str) -> str:
    """RFC 5545 TEXT escaping. A comma in a venue name ends the field otherwise."""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _utc_stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str, limit: int = 73) -> list[str]:
    """Fold long lines at 75 octets, as the spec requires (continuation starts with
    a space). Descriptions from the sheet row are long enough to hit this."""
    if len(line) <= limit:
        return [line]
    out, rest = [line[:limit]], line[limit:]
    while rest:
        out.append(" " + rest[: limit - 1])
        rest = rest[limit - 1:]
    return out


def build_ics(
    *,
    uid: str,
    title: str,
    when_iso: str,
    location: str = "",
    description: str = "",
    url: str = "",
    minutes_before: int = 90,
) -> str:
    """A one-event calendar. `when_iso` must carry an offset (slot_deadline does)."""
    start = dt.datetime.fromisoformat(when_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=IST)
    end = start + dt.timedelta(minutes=60)

    desc = description
    if url:
        desc = f"{desc}\n\n{url}" if desc else url

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Recruit//CDC shortlist//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}@recruit.jaswanth.me",
        f"DTSTAMP:{_utc_stamp(dt.datetime.now(dt.timezone.utc))}",
        f"DTSTART:{_utc_stamp(start)}",
        f"DTEND:{_utc_stamp(end)}",
        f"SUMMARY:{_esc(title)}",
    ]
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    if desc:
        lines.append(f"DESCRIPTION:{_esc(desc)}")
    lines += [
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "BEGIN:VALARM",
        f"TRIGGER:-PT{int(minutes_before)}M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_esc(title)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    # CRLF is mandatory; some clients silently reject LF-only calendars.
    return "\r\n".join(folded) + "\r\n"
