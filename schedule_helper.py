import os
import time as time_module
from datetime import datetime

import discord

from gsheets_helper import get_calendar_entries, parse_time_range, open_worksheet, write_dynamic_schedule_rows

# .env can override this; defaults to a tab named "Static Schedule" in the
# same Google Sheet the live coverage data lives in.
STATIC_SCHEDULE_WORKSHEET_NAME = os.getenv("STATIC_SCHEDULE_WORKSHEET_NAME", "Static Schedule")
DYNAMIC_SCHEDULE_WORKSHEET_NAME = os.getenv(
    "DYNAMIC_SCHEDULE_WORKSHEET_NAME",
    "Dynamic Schedule"
)
# Cached parse, refreshed on a short TTL rather than on every call — this
# tab rarely changes, and re-fetching it on every /coverage, /resolve, and
# /schedule call would burn through Sheets API quota for no reason.
CACHE_TTL_SECONDS = 300
_cache = {"time": 0, "schedule": None}

_static_ws = None
_dynamic_ws = None


def _get_dynamic_worksheet():
    global _dynamic_ws
    if _dynamic_ws is None:
        _dynamic_ws = open_worksheet(DYNAMIC_SCHEDULE_WORKSHEET_NAME)
    return _dynamic_ws


def _get_static_worksheet():
    global _static_ws
    if _static_ws is None:
        _static_ws = open_worksheet(STATIC_SCHEDULE_WORKSHEET_NAME)
    return _static_ws


def _cell(values, row, col):
    """1-indexed lookup into a get_all_values()-style 2D list. None if out of range or blank."""
    r, c = row - 1, col - 1
    if r < 0 or r >= len(values):
        return None
    row_list = values[r]
    if c < 0 or c >= len(row_list):
        return None
    v = row_list[c]
    return v if v != "" else None


def _parse_static_schedule_raw():
    """
    Reads the static schedule tab and returns:
        {
          "CSL": {
            "Monday": [("10:00 - 11:30 AM", ["Ryan"]), ...],
            ...
          },
          "Hackerspace": {...},
        }
    Names are only included when a slot actually has someone in it — an
    "x" in the sheet means the slot isn't in use and is skipped.

    This is a structural parse (looks for location header rows, then day
    columns, then time-slot rows) rather than fixed row/column numbers, so
    it survives the sheet being edited as long as the CSL/Hackerspace +
    day-header + time-slot-row shape stays the same.
    """
    ws = _get_static_worksheet()
    values = ws.get_all_values()
    max_row = len(values)
    max_col = max((len(row) for row in values), default=0)

    schedule = {}
    r = 1
    while r <= max_row:
        location = _cell(values, r, 2)
        if location in ("CSL", "Hackerspace"):
            day_cols = {}
            col = 3
            while col <= max_col:
                day = _cell(values, r, col)
                if day:
                    day_cols[col] = day
                col += 1

            schedule[location] = {}
            r += 1

            while r <= max_row:
                time_label = _cell(values, r, 2)
                if not time_label or time_label in ("CSL", "Hackerspace"):
                    break
                names_by_day = {}
                for col, day in day_cols.items():
                    val = _cell(values, r, col)
                    names_by_day.setdefault(day, []).append(val)
                for day, raw_vals in names_by_day.items():
                    schedule[location].setdefault(day, []).append((time_label, raw_vals))
                r += 1
        else:
            r += 1

    return schedule


def get_static_schedule_raw():
    """Returns the cached raw parse (names/'x'/None per column), re-reading the sheet if the cache has expired."""
    now_ts = time_module.time()
    if _cache["schedule"] is None or now_ts - _cache["time"] > CACHE_TTL_SECONDS:
        _cache["schedule"] = _parse_static_schedule_raw()
        _cache["time"] = now_ts
    return _cache["schedule"]
 
 
def get_static_schedule():
    """
    Filtered view for display: 'x' cells dropped, only real assigned
    names kept. Derived from the same cached raw read as
    get_static_schedule_raw(), so this doesn't cost an extra Sheets call.
    """
    raw = get_static_schedule_raw()
    filtered = {}
    for location, days in raw.items():
        filtered[location] = {}
        for day, slots in days.items():
            filtered[location][day] = [
                (time_label, [n for n in raw_vals if n and str(n).strip().lower() != "x"])
                for time_label, raw_vals in slots
            ]
    return filtered



def _time_key(time_str, date_str):
    """
    Normalizes a time-range string to a comparable (start, end) tuple by
    running it through the same parser gsheets_helper uses, so "7-9pm" and
    "7:00 - 9:00 PM" are recognized as the same slot despite being written
    differently.
    """
    try:
        start, end = parse_time_range(time_str, date_str)
        return (start.hour, start.minute, end.hour, end.minute)
    except Exception:
        return None


def _live_by_key(target_date):
    date_str_slash = target_date.strftime("%m/%d")
    date_str_dash = f"{target_date.year}-{target_date.month:02d}-{target_date.day:02d}"
    live_today = [r for r in get_calendar_entries() if r.get("Date") == date_str_slash]

    by_key = {}
    for r in live_today:
        key = (str(r.get("Location", "")).strip().lower(), _time_key(r.get("Time", ""), date_str_dash))
        by_key[key] = r
    return by_key, date_str_dash


def build_daily_schedule_lines(target_date=None):
    """
    Returns a list of text lines: the full day's shifts for every
    location, each slot annotated with live coverage status if there's a
    matching row in the sheet for that day.
    """
    if target_date is None:
        target_date = datetime.now()

    day_name = target_date.strftime("%A")
    static = get_static_schedule()
    live_by_key, date_str_dash = _live_by_key(target_date)

    lines = [f"Schedule for {day_name}, {target_date.strftime('%m/%d')}", ""]
    for location in ("CSL", "Hackerspace"):
        lines.append(f"{location}:")
        slots = static.get(location, {}).get(day_name, [])
        if not slots:
            lines.append("  No shifts scheduled")
        for time_range, assigned in slots:
            assigned_str = ", ".join(assigned) if assigned else "unfilled"
            key = (location.lower(), _time_key(time_range, date_str_dash))
            live = live_by_key.get(key)
            if live:
                status = live.get("Status", "")
                who = live.get("AssigneeID") or ""
                if status == "Needs Coverage":
                    lines.append(f"  • {time_range} — {assigned_str} — ⚠️ coverage needed")
                elif status == "Covered" and who:
                    lines.append(f"  • {time_range} — {assigned_str} — ✅ covered by {who}")
                elif status:
                    lines.append(f"  • {time_range} — {assigned_str} — {status}")
                else:
                    lines.append(f"  • {time_range} — {assigned_str}")
            else:
                lines.append(f"  • {time_range} — {assigned_str}")
        lines.append("")
    return lines


def build_daily_schedule_embed(target_date=None):
    """Same content as build_daily_schedule_lines, formatted as a Discord embed."""
    if target_date is None:
        target_date = datetime.now()

    day_name = target_date.strftime("%A")
    static = get_static_schedule()
    live_by_key, date_str_dash = _live_by_key(target_date)

    embed = discord.Embed(
        title=f"Schedule — {day_name}, {target_date.strftime('%m/%d')}",
        color=discord.Color.blurple(),
    )

    for location in ("CSL", "Hackerspace"):
        slots = static.get(location, {}).get(day_name, [])
        if not slots:
            embed.add_field(name=location, value="No shifts scheduled", inline=False)
            continue

        rows = []
        for time_range, assigned in slots:
            assigned_str = ", ".join(assigned) if assigned else "unfilled"
            key = (location.lower(), _time_key(time_range, date_str_dash))
            live = live_by_key.get(key)
            if live:
                status = live.get("Status", "")
                who = live.get("AssigneeID") or ""
                if status == "Needs Coverage":
                    rows.append(f"**{time_range}** — {assigned_str} — ⚠️ coverage needed")
                elif status == "Covered" and who:
                    rows.append(f"**{time_range}** — {assigned_str} — ✅ covered by {who}")
                elif status:
                    rows.append(f"**{time_range}** — {assigned_str} — {status}")
                else:
                    rows.append(f"**{time_range}** — {assigned_str}")
            else:
                rows.append(f"**{time_range}** — {assigned_str}")

        embed.add_field(name=location, value="\n".join(rows), inline=False)

    return embed


def build_daily_dynamic_rows(target_date=None):
    """
    Builds the flat row list for the dynamic-schedule block (Coverage tab,
    rows 4-16): one row per assigned person for today's real (non-'x')
    slots, annotated with any live coverage override. Row keys match
    gsheets_helper.HEADERS: AssigneeID, Day, Date, Time, Location, Status,
    ThreadID.
 
    A slot with 2 SCMs produces 2 rows. A slot with no name in a given
    column but that isn't 'x' is a real, unfilled shift -> one row with
    AssigneeID blank and Status "Needs Coverage".
 
    NOTE: a coverage override is matched by (location, time, date) only —
    there's no field recording *which* of a slot's up-to-two static
    assignees the request was for. If a slot has an override, it's
    applied to the first row generated for that slot; a second assignee
    on the same slot still shows as plain "Scheduled".
    """
    if target_date is None:
        target_date = datetime.now()
 
    day_name = target_date.strftime("%A")
    date_str = target_date.strftime("%m/%d")
 
    raw_static = get_static_schedule_raw()
    live_by_key, date_str_dash = _live_by_key(target_date)
 
    rows = []
    for location in ("CSL", "Hackerspace"):
        slots = raw_static.get(location, {}).get(day_name, [])
        for time_range, raw_vals in slots:
            # Real slot = at least one column isn't 'x'. All-'x' means
            # this isn't a shift that day at all -- skip it entirely.
            real_vals = [v for v in raw_vals if not (v and str(v).strip().lower() == "x")]
            if not real_vals:
                continue
 
            key = (location.lower(), _time_key(time_range, date_str_dash))
            override = live_by_key.get(key)
            override_applied = False
 
            for v in real_vals:
                assignee = v or ""
                status = "Scheduled" if assignee else "Needs Coverage"
                thread_id = ""
 
                if override and not override_applied:
                    if override.get("Status") == "Covered":
                        assignee = override.get("AssigneeID") or assignee
                        status = "Covered"
                    elif override.get("Status") == "Needs Coverage":
                        status = "Needs Coverage"
                    thread_id = override.get("ThreadID", "")
                    override_applied = True
 
                rows.append({
                    "AssigneeID": assignee,
                    "Day": day_name,
                    "Date": date_str,
                    "Time": time_range,
                    "Location": location,
                    "Status": status,
                    "ThreadID": thread_id,
                })
 
    return rows


def write_daily_dynamic_schedule(target_date=None):
    """Builds today's dynamic-schedule rows and writes them into the Coverage tab."""
    rows = build_daily_dynamic_rows(target_date)
    write_dynamic_schedule_rows(rows)
    return rows
    