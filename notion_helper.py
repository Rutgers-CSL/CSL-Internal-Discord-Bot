import asyncio
import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from notion_client import Client
import os
import re
from zoneinfo import ZoneInfo
from thread_page_mapping import get_page_id_for_thread, set_page_id_for_thread, delete_thread_mapping

load_dotenv()
LOCAL_TZ = ZoneInfo("America/New_York")

notion = Client(auth=os.getenv("NOTION_TOKEN"))
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def get_data_source_id():
    db = notion.databases.retrieve(database_id=DATABASE_ID)
    return db["data_sources"][0]["id"]

DATA_SOURCE_ID = get_data_source_id()

def get_calendar_entries():
    response = notion.data_sources.query(
    data_source_id=DATA_SOURCE_ID
    )
    return response["results"]

def get_shifts_needing_coverage():
    response = notion.data_sources.query(
        data_source_id=DATA_SOURCE_ID,
        filter={
            "property": "Status",
            "select": {"equals": "Needs Coverage"}
        }
    )
    return response["results"]

def get_todays_shifts():
    today = datetime.now().strftime("%Y-%m-%d")
    response = notion.data_sources.query(
        data_source_id=DATA_SOURCE_ID,
        filter={
            "property": "Date",
            "date": {"equals": today}
        }
    )
    return response["results"]

def resolve_partial_shift(page_id, day, date, full_time, covered_time, location, assignee_id=None):
    """
    Splits a shift into a covered event and remaining uncovered event(s).
    full_time: original shift time range string, e.g. "7-9pm"
    covered_time: the portion being claimed, e.g. "7-8pm"
    """
    year = datetime.now().year
    date_str = f"{year}-{date.replace('/', '-')}"

    full_start, full_end = parse_time_range(full_time, date_str)
    covered_start, covered_end = parse_time_range(covered_time, date_str)

    # Sanity check: covered range must fall within the full shift
    if covered_start < full_start or covered_end > full_end:
        raise ValueError(f"Covered time {covered_time} is outside the shift range {full_time}")

    # Archive the original event since it's being replaced
    notion.pages.update(page_id=page_id, archived=True)

    # Create the covered event (status = Covered, not "Needs Coverage")
    create_notion_event(
        day, date,
        format_time_range(covered_start, covered_end),
        location,
        status="Covered",
        assignee_id=assignee_id
    )

    remainder_times = []
    if covered_start > full_start:
        remainder_times.append(format_time_range(full_start, covered_start))
    if covered_end < full_end:
        remainder_times.append(format_time_range(covered_end, full_end))
    # # Remainder before the covered chunk (e.g. covered chunk starts later than shift start)
    # if covered_start > full_start:
    #     remainder_times = format_time_range(full_start, covered_start)
    #     create_notion_event(
    #         day, date,
    #         format_time_range(full_start, covered_start),
    #         location,
    #         status="Needs Coverage"
    #     )

    # # Remainder after the covered chunk (e.g. covered chunk ends before shift end)
    # if covered_end < full_end:
    #     remainder_times = format_time_range(covered_end, full_end)
    #     create_notion_event(
    #         day, date,
    #         format_time_range(covered_end, full_end),
    #         location,
    #         status="Needs Coverage"
    #     )
    return remainder_times  # list of strings like ["7:00pm-8:00pm", "8:30pm-9:00pm"] for any remaining uncovered portions


def format_time_range(start_dt, end_dt):
    """Turns two datetimes back into a display string like '7:00pm-8:00pm'."""
    def fmt(dt):
        return dt.strftime("%-I:%M%p").lower().replace(":00", "")
    return f"{fmt(start_dt)}-{fmt(end_dt)}"
# parses time ranges so that notion events can be created with proper start and end times
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

def create_notion_event(day, date, time, location, status="Needs Coverage", assignee_id=None):
    year = datetime.now().year
    date_str = f"{year}-{date.replace('/', '-')}"

    start_dt, end_dt = parse_time_range(time, date_str)
    start_dt = start_dt.replace(tzinfo=LOCAL_TZ)
    end_dt = end_dt.replace(tzinfo=LOCAL_TZ)

    properties={
        "Name": {"title": [{"text": {"content": f"{day} {date} {time} in {location}"}}]},
        "Date": {
            "date": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            }
        },
        "Location": {"select": {"name": location}},
        "Status": {"select": {"name": status}},
    }
        
    if assignee_id:
        properties["Assignee"] = {"people": [{"id": assignee_id}]}

    return notion.pages.create(
        parent={"data_source_id": DATA_SOURCE_ID},
        properties=properties
    )


async def create_shift_thread(channel, day, date, time, location):
    """
    Creates a coverage thread in the given channel + a matching Notion page,
    and stores the thread<->page mapping.
    Returns the created thread.
    """
    thread_name = f"{day} {date} {time} in {location}"
    thread = await channel.create_thread(
        name=thread_name,
        type=discord.ChannelType.public_thread
    )
    page = await asyncio.to_thread(create_notion_event, day, date, time, location)
    set_page_id_for_thread(thread.id, page["id"])
    return thread, page

def list_notion_users():
    response = notion.users.list()
    for user in response["results"]:
        print(user["id"], user.get("name"))

if __name__ == "__main__":
        entries = get_calendar_entries()  # or no await if it's sync
        create_notion_event("Monday", "09/15", "3-5pm", "CSL")
        list_notion_users()
        #print(entries)
