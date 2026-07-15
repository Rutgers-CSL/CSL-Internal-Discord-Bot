import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from notion_client import Client
import os

load_dotenv()

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

def resolve_shift(page_id, assignee_name):
    notion.pages.update(
        page_id=page_id,
        properties={
            "Status": {"select": {"name": "Covered"}},
            "Assignee": {"rich_text": [{"text": {"content": assignee_name}}]}
        }
    )

def create_notion_event(day, date, time, location):
    year = datetime.now().year
    notion.pages.create(
        parent={"data_source_id": DATA_SOURCE_ID},
        properties={
            "Name": {"title": [{"text": {"content": f"{day} {date} {time} in {location}"}}]},
            "Date": {"date": {"start": f"{year}-{date.replace('/', '-')}"}},
            "Location": {"select": {"name": location}},
            "Status": {"select": {"name": "Needs Coverage"}},
        }
    )




if __name__ == "__main__":
        entries = get_calendar_entries()  # or no await if it's sync
        create_notion_event("Monday", "09/15", "3:00 PM", "CSL")
        print(entries)
