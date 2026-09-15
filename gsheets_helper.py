import asyncio
import uuid
import discord
import logging
from dotenv import load_dotenv
from datetime import datetime
import os
import re
from zoneinfo import ZoneInfo
import gspread

load_dotenv()
LOCAL_TZ = ZoneInfo("America/New_York")

# Sheet setup

SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Coverage")

_gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
_sh = _gc.open_by_key(SHEET_ID)
worksheet = _sh.worksheet(WORKSHEET_NAME)

def open_worksheet(name):
    """Opens another tab in the same spreadsheet (e.g. the static schedule tab)."""
    return _sh.worksheet(name)

# the order the columns are in the sheet, starting from column B (column A is ignored)
HEADERS = ["AssigneeID", "Day", "Date", "Time", "Location", "Status", "ThreadID"]
HEADER_ROW = 19
HEADER_COL = 2  # column B
DATA_START_ROW = HEADER_ROW + 1
 
 
def _col(name):
    return HEADER_COL + HEADERS.index(name)
 
 
def _col_letter(col_num):
    # Converts a 1-indexed column number to its A1 letter(s), e.g. 2 -> 'B'
    letters = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
 
 
END_COL_LETTER = _col_letter(HEADER_COL + len(HEADERS) - 1)  # last column, e.g. 'J'


# --- Dynamic schedule block (top of the Coverage tab, rows 3-16) ---
# Row 3 holds the header (same HEADERS as the log below); rows 4-16 are the
# 13 rows available for today's merged static+coverage schedule.
DYNAMIC_HEADER_ROW = 3
DYNAMIC_DATA_START_ROW = 4
DYNAMIC_DATA_END_ROW = 16
DYNAMIC_MAX_ROWS = DYNAMIC_DATA_END_ROW - DYNAMIC_DATA_START_ROW + 1  # 13
 
 
def write_dynamic_schedule_rows(rows):
    """
    Overwrites the dynamic-schedule block (rows 4-16) with the given list
    of row-dicts, keyed like HEADERS. Pads with blank rows so leftover
    rows from a previous day's write get cleared out, and truncates
    silently if more than DYNAMIC_MAX_ROWS (13) rows are passed in.
    """
    rows = rows[:DYNAMIC_MAX_ROWS]
    values = [[r.get(h, "") for h in HEADERS] for r in rows]
    while len(values) < DYNAMIC_MAX_ROWS:
        values.append([""] * len(HEADERS))
 
    rng = f"{_col_letter(HEADER_COL)}{DYNAMIC_DATA_START_ROW}:{END_COL_LETTER}{DYNAMIC_DATA_END_ROW}"
    worksheet.update(rng, values, value_input_option="USER_ENTERED")



def _get_records():
    #reads table starting at HEADER_ROW/HEADER_COL and returns a list of dicts keyed by HEADERS, 
    # in sheet order. Reads by position, not by matching header text, 
    # so it doesn't care what's in column A.
 
    rng = f"{_col_letter(HEADER_COL)}{DATA_START_ROW}:{END_COL_LETTER}"
    values = worksheet.get(rng)
    records = []
    for row in values:
        row = row + [""] * (len(HEADERS) - len(row))  # pad short/ragged rows
        records.append(dict(zip(HEADERS, row)))
    return records
 
 
# Reads 
 
def get_calendar_entries():
    return _get_records()




 
def get_shifts_needing_coverage():
    return [r for r in _get_records() if r.get("Status") == "Needs Coverage"]
 
 
def get_todays_shifts():
    today = datetime.now().strftime("%m/%d")
    return [r for r in _get_records() if r.get("Date") == today]
 
 
def find_row_by_threadid(thread_id):
    """
    Returns (row_index, record_dict) for the row whose ThreadID matches, or
    (None, None) if not found. row_index is the sheet's actual row number
    (already accounting for the header offset), so it can be passed
    straight to update_cell.
    """
    records = _get_records()
    for i, record in enumerate(records):
        if str(record.get("ThreadID")) == str(thread_id):
            return DATA_START_ROW + i, record
    return None, None
 
 
# Writes 
 
def set_row_status(row_index, status, assignee_id=None):
    worksheet.update_cell(row_index, _col("Status"), status)
    if assignee_id:
        worksheet.update_cell(row_index, _col("AssigneeID"), assignee_id)
 
def create_sheet_event(day, date, time, location, status="Needs Coverage", assignee_id="", thread_id=""):
    """
    Appends a new row for a shift, directly below the last row of the table
    (not using append_row, since that defaults to column A). Returns the
    row as a dict.
    """
    assignee_id = assignee_id #or str(uuid.uuid4())  # generate a unique ID if not provided
    name = f"{day} {date} {time} in {location}"
    row_values = [assignee_id, day, date, time, location, status, str(thread_id)]
 
    next_row = DATA_START_ROW + len(_get_records())
    rng = f"{_col_letter(HEADER_COL)}{next_row}:{END_COL_LETTER}{next_row}"
    worksheet.update(rng, [row_values], value_input_option="USER_ENTERED")
 
    return dict(zip(HEADERS, row_values))
 
 
# --- Date / time parsing (unchanged — pure logic, no backend dependency) --
 
def parse_shift_date(date: str):
    """Returns a datetime if valid MM/DD, else None."""
    try:
        return datetime.strptime(date, "%m/%d")
    except ValueError:
        return None
 
 
def format_time_range(start_dt, end_dt):
    """Turns two datetimes back into a display string like '7:00pm-8:00pm'."""
    def fmt(dt):
        return dt.strftime("%-I:%M%p").lower().replace(":00", "")
    return f"{fmt(start_dt)}-{fmt(end_dt)}"
 
 
def parse_time_range(time_str, date_str):
    """
    Parses strings like '7-9pm', '11:30am-1pm', '8pm-9pm', '11:30-1pm'
    into (start_datetime, end_datetime).
    """
    time_str = time_str.lower().replace(" ", "")
    start_str, end_str = time_str.split("-")
 
    pattern = r'(\d{1,2})(?::(\d{2}))?(am|pm)?'
 
    def parse_piece(piece, meridiem_override=None):
        match = re.match(pattern, piece)
        hour, minute, meridiem = match.groups()
        hour = int(hour)
        minute = int(minute) if minute else 0
        meridiem = meridiem or meridiem_override
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return hour, minute
 
    end_match = re.match(pattern, end_str)
    end_meridiem = end_match.group(3)
    start_has_explicit_meridiem = re.match(pattern, start_str).group(3) is not None
 
    end_hour, end_min = parse_piece(end_str)
 
    # First guess: borrow the end's meridiem for the start
    start_hour, start_min = parse_piece(start_str, meridiem_override=end_meridiem)
 
    base = datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = base.replace(hour=start_hour, minute=start_min)
    end_dt = base.replace(hour=end_hour, minute=end_min)
 
    # If start ended up after end, and the start had no explicit am/pm,
    # the borrowed meridiem was wrong (e.g. "11:30-1pm" -> flip to am)
    if start_dt >= end_dt and not start_has_explicit_meridiem:
        flipped_meridiem = "am" if end_meridiem == "pm" else "pm"
        start_hour, start_min = parse_piece(start_str, meridiem_override=flipped_meridiem)
        start_dt = base.replace(hour=start_hour, minute=start_min)
 
    return start_dt, end_dt
 
 
# Shift resolution 
 
def resolve_full_shift(thread_id, assignee_id=None):
    """Marks the whole shift as Covered."""
    row_index, record = find_row_by_threadid(thread_id)
    if row_index is None:
        raise ValueError("Couldn't find this shift in the sheet.")
    set_row_status(row_index, "Covered", assignee_id)
 
 
def resolve_partial_shift(thread_id, day, date, full_time, covered_time, location, assignee_id=None):
    """
    Marks the covered portion of a shift as Covered and returns a list of
    remaining uncovered time-range strings (e.g. ["6-7pm", "8-10pm"]) so the
    caller can spin up new threads/rows for whatever's left.
    """
    year = datetime.now().year
    date_str = f"{year}-{date.replace('/', '-')}"
 
    full_start, full_end = parse_time_range(full_time, date_str)
    covered_start, covered_end = parse_time_range(covered_time, date_str)
 
    if covered_start < full_start or covered_end > full_end:
        raise ValueError(f"Covered time {covered_time} is outside the shift range {full_time}")
 
    row_index, record = find_row_by_threadid(thread_id)
    if row_index is None:
        raise ValueError("Couldn't find this shift in the sheet.")
 
    set_row_status(row_index, "Covered", assignee_id)
    worksheet.update_cell(row_index, _col("Time"), covered_time)
 
    remainder_times = []
    if covered_start > full_start:
        remainder_times.append(format_time_range(full_start, covered_start))
    if covered_end < full_end:
        remainder_times.append(format_time_range(covered_end, full_end))
 
    return remainder_times
 

 
# Discord thread creation 
 
async def create_shift_thread(channel, day, date, time, location):
    """
    Creates a coverage thread in the given channel + a matching sheet row
    (with the thread's ID stored directly in the ThreadID column).
    Returns (thread, row_dict).
    """
    thread_name = f"{day} {date} {time} in {location}"
    thread = await channel.create_thread(
        name=thread_name,
        type=discord.ChannelType.public_thread
    )
    row = await asyncio.to_thread(
        create_sheet_event, day, date, time, location, "Needs Coverage", "", thread.id
    )
    return thread, row
 
 
if __name__ == "__main__":
    print(get_calendar_entries())
    print(create_sheet_event("Monday", "09/15", "3-5pm", "CSL"))
 